# Copyright (C) 2025 ByteDance Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import math
import os
from typing import Dict, List, Union
from btrace.pb import perfetto_pb2
from btrace.model import CPUSample, MethodNode, MethodTree, PerfettoCounterInfo, PerfettoSliceInfo, SymbolInfo, TraceRawContent

        
PACKET_SEQ_ID = 1

class AutoIncrease:
    def __init__(self):
        self.val = 0

    def get(self):
        self.val += 1
        return self.val

    def reset(self):
        self.val = 0

# 自定义切片（阶段标注 / 异步等待 / hitch-hang）的配对问题（2026-10-19）：
# Perfetto 对「同步切片」（TYPE_SLICE_BEGIN/END 打在一条轨道上）是按「时间排序后的栈」配对的，
# 同一轨道上并发的区间排序后是 B B B E E…，于是时长会互相错配（实测：一条真实 224ms 的请求
# 被画成 83ms、302ms 的变成 38ms）。也试过 legacy 异步切片（phase 'b'/'e' + unscoped_id），
# 但 TP 会把它们按切片名重挂到全局异步轨道集，泳道名（request_waterfall 之类）就没了，冷启动那种
# 上百条并发等待会散成上百条轨道。
# 最终做法：**在转换器里先做一次分层**（贪心区间划分，同层区间严格不重叠），每层一条轨道，
# 同层不重叠 → 配对必然正确，泳道名保留（第 2 层起叫 `<type> #2`、`#3`…）。
# 层数 > LANE_CAP（默认 300）时，只画最长的那些层，其余在首条位置给一个 instant 标记说明少画了多少条。
# BTRACE_PB_SYNC_SLICES=1 可退回旧行为（一条轨道堆叠，重叠时长度不可信）。
ASYNC_SLICES = os.environ.get("BTRACE_PB_SYNC_SLICES", "").strip().lower() not in ("1", "true", "on", "yes")

LANE_CAP = int(os.environ.get("BTRACE_PB_LANE_CAP", "300") or 300)

# 同一 type 下「同名且重复次数很多」的区间（典型：cookie 同步这种每次变更都 schedule 一次的防抖等待，
# 一次冷启动能积几百条），逐条画只是把图淹掉、信息量为零。超过该阈值就合成一条汇总区间：
# 区间取 [最早开始, 最晚结束]，名字前加 `×N`，debug 里带 count / waited 的 p50、min、max。
# 0 = 不合并。原始记录仍在 sqlite 里，不丢数据。
MERGE_MIN = int(os.environ.get("BTRACE_PB_MERGE_MIN", "20") or 0)


def merge_repeats(items: List[PerfettoSliceInfo]) -> List[PerfettoSliceInfo]:
    """把同名高频区间合成一条汇总（只影响 pb 的展示，sqlite 里的逐条记录不变）"""
    if not MERGE_MIN:
        return items
    by_name = collections.defaultdict(list)
    for item in items:
        by_name[item.name or item.type].append(item)
    out = []
    for name, group in by_name.items():
        if len(group) <= MERGE_MIN:
            out.extend(group)
            continue
        vals = sorted((x.end_time - x.begin_time) / 1000.0 for x in group)
        debug = dict(group[0].debug_info or {})
        debug.update({
            "merged": True,
            "count": len(group),
            "waited_ms_p50": round(vals[len(vals) // 2], 1),
            "waited_ms_min": round(vals[0], 1),
            "waited_ms_max": round(vals[-1], 1),
        })
        out.append(PerfettoSliceInfo(
            group[0].type,
            min(x.begin_time for x in group),
            max(x.end_time for x in group),
            f"×{len(group)} {name}",
            debug,
        ))
    return out


def plan_lanes(items: List[PerfettoSliceInfo]):
    """把同一 type 的区间按时间分层：同层严格不重叠（零宽标记不占层）。

    返回 (lanes, dropped)：lanes = [[PerfettoSliceInfo, ...], ...]，层数 = 该 type 的并发度；
    dropped = 因 LANE_CAP 没画的区间（调用方给一条 instant 说明）。
    """
    lanes: List[List[PerfettoSliceInfo]] = []
    lane_ends: List[int] = []
    for item in sorted(items, key=lambda x: (x.begin_time, x.end_time)):
        if item.end_time <= item.begin_time:          # 零宽标记：不会和任何区间交叉，放第一层
            if not lanes:
                lanes.append([]); lane_ends.append(item.end_time)
            lanes[0].append(item)
            continue
        for d, last_end in enumerate(lane_ends):
            if item.begin_time > last_end:            # 严格不重叠（同刻相接也换层，避免同 ts 事件歧义）
                lanes[d].append(item); lane_ends[d] = item.end_time
                break
        else:
            lanes.append([item]); lane_ends.append(item.end_time)

    if LANE_CAP and len(lanes) > LANE_CAP:
        # 保留"最长区间"所在的层，其余丢掉并在图上标出来（宁可少画，也不画错）
        def lane_weight(lane):
            return max((x.end_time - x.begin_time) for x in lane)
        keep = sorted(range(len(lanes)), key=lambda d: lane_weight(lanes[d]), reverse=True)[:LANE_CAP]
        keep_set = set(keep)
        dropped = [x for d, lane in enumerate(lanes) if d not in keep_set for x in lane]
        lanes = [lanes[d] for d in sorted(keep_set)]
    else:
        dropped = []
    return lanes, dropped


def gen_instant_event_packet(uuid: int, timestamp: int, name: str) -> perfetto_pb2.TracePacket:
    """零宽标记（instant）：渲染成竖线 + 名字，没有时长语义"""
    track_event = perfetto_pb2.TrackEvent(type=perfetto_pb2.TrackEvent.Type.TYPE_INSTANT,
                                          track_uuid=uuid)
    track_event.name = name
    event_packet = perfetto_pb2.TracePacket(timestamp=timestamp)
    event_packet.track_event.CopyFrom(track_event)
    event_packet.trusted_packet_sequence_id = PACKET_SEQ_ID
    return event_packet


def gen_root_packet(uuid: int) -> perfetto_pb2.TracePacket:
    child_ordering = perfetto_pb2.TrackDescriptor.ChildTracksOrdering.EXPLICIT
    root_track = perfetto_pb2.TrackDescriptor(uuid=uuid, name='Root', child_ordering=child_ordering)
    root_packet = perfetto_pb2.TracePacket()
    root_packet.track_descriptor.CopyFrom(root_track)

    return root_packet

def gen_process_packet(uuid: int, pid: int, process_name: str, parent_uuid: int) -> perfetto_pb2.TracePacket:
    process = perfetto_pb2.ProcessDescriptor(pid=pid, process_name=process_name)
    process_track = perfetto_pb2.TrackDescriptor(uuid=uuid, process=process, parent_uuid=parent_uuid)
    process_packet = perfetto_pb2.TracePacket()
    process_packet.track_descriptor.CopyFrom(process_track)

    return process_packet

def gen_sub_packet(uuid: int, parent_uuid: int, name: str) -> perfetto_pb2.TracePacket:
    sub_track = perfetto_pb2.TrackDescriptor(uuid=uuid, name=name, parent_uuid=parent_uuid)
    sub_packet = perfetto_pb2.TracePacket()
    sub_packet.track_descriptor.CopyFrom(sub_track)

    return sub_packet

def gen_thread_packet(uuid: int, pid: int, tid: int, thread_name: str) -> perfetto_pb2.TracePacket:
    thread = perfetto_pb2.ThreadDescriptor(pid=pid, tid=tid, thread_name=thread_name)
    thread_track = perfetto_pb2.TrackDescriptor(uuid=uuid, thread=thread)
    thread_packet = perfetto_pb2.TracePacket()
    thread_packet.track_descriptor.CopyFrom(thread_track)

    return thread_packet

def gen_counter_packet(uuid: int, parent_uuid: int, name: str) -> perfetto_pb2.TracePacket:
    counter = perfetto_pb2.CounterDescriptor()
    counter_track = perfetto_pb2.TrackDescriptor(uuid=uuid, parent_uuid=parent_uuid, name=name, counter=counter, sibling_order_rank=-1)
    counter_packet = perfetto_pb2.TracePacket()
    counter_packet.track_descriptor.CopyFrom(counter_track)

    return counter_packet

def gen_debug_annotation(k: str, v: object) -> perfetto_pb2.DebugAnnotation:
    annotation = perfetto_pb2.DebugAnnotation()
    annotation.name = k
    
    if isinstance(v, int):
        annotation.int_value = v
    elif isinstance(v, str):
        annotation.string_value = v

    return annotation

def gen_slice_event_packet(uuid: int, timestamp: int, name: str, event_type: perfetto_pb2.TrackEvent.Type, debug_infos: Dict=None) -> perfetto_pb2.TracePacket:
    track_event = perfetto_pb2.TrackEvent(type=event_type, track_uuid=uuid)

    debug_annotations: List[perfetto_pb2.DebugAnnotation] = []
    if debug_infos:
        for k, v in debug_infos.items():
            annotation = gen_debug_annotation(k, v)
            debug_annotations.append(annotation)

    track_event.debug_annotations.extend(debug_annotations)
    
    if event_type == perfetto_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN:
        track_event.name = name

    event_packet = perfetto_pb2.TracePacket(timestamp=timestamp)
    event_packet.track_event.CopyFrom(track_event)
    event_packet.trusted_packet_sequence_id = PACKET_SEQ_ID
    
    return event_packet

def gen_counter_event_packet(uuid: int, timestamp: int, counter_value: Union[int, float], debug_infos: Dict=None) -> perfetto_pb2.TracePacket:
    event_type = perfetto_pb2.TrackEvent.Type.TYPE_COUNTER
    track_event = perfetto_pb2.TrackEvent(type=event_type, track_uuid=uuid)
    
    if isinstance(counter_value, int):
        track_event.counter_value = counter_value
    elif isinstance(counter_value, float):
        track_event.double_counter_value = counter_value

    debug_annotations: List[perfetto_pb2.DebugAnnotation] = []
    if debug_infos:
        for k, v in debug_infos.items():
            annotation = gen_debug_annotation(k, v)
            debug_annotations.append(annotation)

    track_event.debug_annotations.extend(debug_annotations)

    event_packet = perfetto_pb2.TracePacket(timestamp=timestamp)
    event_packet.track_event.CopyFrom(track_event)
    event_packet.trusted_packet_sequence_id = PACKET_SEQ_ID
    
    return event_packet


def method_tree_to_trace(trace_packet_list: List[perfetto_pb2.TracePacket], thread_track: perfetto_pb2.TrackDescriptor, method_tree: MethodTree, method_node: MethodNode, addr_symbol_map: Dict[int, SymbolInfo]):
    symbol_info = addr_symbol_map[method_node.address]
    symbol_name = symbol_info.name

    start_time = (method_node.start_time+method_tree.start_time) * 1000
    cpu_time = method_node.end_cpu_time - method_node.start_cpu_time
    cpu_time_s = math.floor(cpu_time / 1_000_000)
    cpu_time_ms = math.floor((cpu_time - cpu_time_s * 1_000_000)/ 1000)
    cpu_time_us = cpu_time % 1000
    cpu_time_str = ""
    alloc_size = method_node.end_alloc_size - method_node.start_alloc_size
    alloc_count = method_node.end_alloc_count - method_node.start_alloc_count
    
    if cpu_time_us:
        cpu_time_str = f"{cpu_time_us:3d}us"
    if cpu_time_ms:
        cpu_time_str = f"{cpu_time_ms}ms " + cpu_time_str
    if cpu_time_s:
        cpu_time_str = f"{cpu_time_s}s " + cpu_time_str

    debug_infos = {
        "image": symbol_info.image,
        "file": symbol_info.file,
        "cpu_time": cpu_time_str,
        "cpu_time_int": cpu_time,
        "alloc_size": alloc_size,
        "alloc_count": alloc_count
    }
    
    if method_node.unlock_contention_list:
        contention_tids = [str(x.tid) for x in method_node.unlock_contention_list]
        debug_infos["locked_by"] = ", ".join(contention_tids)
        debug_infos["lock_id"] = str(method_node.unlock_contention_list[0].id)
        symbol_name = symbol_name + "(lock_contention)"

    start_packet = gen_slice_event_packet(thread_track.uuid, start_time, symbol_name, perfetto_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN, debug_infos)
    trace_packet_list.append(start_packet)
    
    for child in method_node.children:
        method_tree_to_trace(trace_packet_list, thread_track, method_tree, child, addr_symbol_map)
    
    end_time = (method_node.end_time+method_tree.start_time) * 1000
    end_packet = gen_slice_event_packet(thread_track.uuid, end_time, symbol_name, perfetto_pb2.TrackEvent.Type.TYPE_SLICE_END)
    trace_packet_list.append(end_packet)

def gen_perfetto_trace(method_tree_list: List[MethodTree], 
                       addr_symbol_map: Dict[int, SymbolInfo],
                       raw_content: TraceRawContent) -> perfetto_pb2.Trace:

    trace = perfetto_pb2.Trace()
    trace_packet_list: List[perfetto_pb2.TracePacket] = []

    auto_increase = AutoIncrease()
    
    root_packet = gen_root_packet(auto_increase.get())
    trace_packet_list.append(root_packet)
    root_uuid = root_packet.track_descriptor.uuid

    bundle_id = raw_content.bundle_id or "Aweme"
    process_packet = gen_process_packet(auto_increase.get(), 1, bundle_id, root_uuid)
    trace_packet_list.append(process_packet)
    process = process_packet.track_descriptor.process
     
    slice_info_map = raw_content.slice_info_map
    counter_info_map = raw_content.counter_info_map
        
    for counter_name, v in counter_info_map.items():
        counter_info_list: List[PerfettoCounterInfo] = v
        counter_packet = gen_counter_packet(auto_increase.get(), root_uuid, f"{counter_name}")
        trace_packet_list.append(counter_packet)
        
        for counter_info in counter_info_list:
            counter_track = counter_packet.track_descriptor
            time = (counter_info.start_time - raw_content.start_time) * 1000
            val = counter_info.val
            counter_event = gen_counter_event_packet(counter_track.uuid, time, val)
            trace_packet_list.append(counter_event)
            
    def _type_order(item):
        name = item[0]
        fixed = {"request_waterfall": 0}      # 网络请求瀑布置顶，读图顺序稳定
        return (fixed.get(name, 1), name)

    for slice_type, v in sorted(slice_info_map.items(), key=_type_order):
        display_name = "Request 瀑布" if slice_type == "request_waterfall" else slice_type
        slice_info_list: List[PerfettoSliceInfo] = merge_repeats(v)
        if ASYNC_SLICES:
            lanes, dropped = plan_lanes(slice_info_list)
            if dropped:
                print(f"[pb] {slice_type}: 并发 {len(lanes) + 1} 层超过 LANE_CAP={LANE_CAP}，"
                      f"只画最长的 {len(lanes)} 层，另有 {len(dropped)} 条未画")
        else:
            lanes, dropped = [slice_info_list], []       # 旧行为：一条轨道全堆叠

        # 多层时先建一个同名父轨道，各层挂在它下面：Perfetto 里是个可折叠的组，
        # 不会和主线程、其它类型交错（单层就保持原来的一条轨道，不改老观感）
        group_uuid = root_uuid
        if len(lanes) > 1:
            group_packet = gen_sub_packet(auto_increase.get(), root_uuid, display_name)
            trace_packet_list.append(group_packet)
            group_uuid = group_packet.track_descriptor.uuid

        # 层的名字按层数补零（`#01..#33`、`#001..#222`）：Perfetto 对同一父轨道下的子轨道按
        # 名字字符串排序，不补零会变成 #1、#10、#11…、#2、#20…（2026-10-19 踩过）。
        lane_width = len(str(len(lanes)))
        for lane_index, lane_items in enumerate(lanes, start=1):
            # 显示名留给父轨道：查看页按显示名复制父轨道即可整组带走，不会因为「层也叫同名」
            # 而被单独复制一遍造成重复/交错；单层（没有组）就直接用显示名。
            lane_name = (display_name if len(lanes) == 1
                         else f"#{lane_index:0{lane_width}d}")
            slice_packet = gen_sub_packet(auto_increase.get(), group_uuid, lane_name)
            trace_packet_list.append(slice_packet)
            slice_track = slice_packet.track_descriptor

            # 被 LANE_CAP 丢掉的：在首条位置给一个 instant，说明少画了多少（不静默丢数据）
            if lane_index == 1 and dropped:
                durs = sorted((x.end_time - x.begin_time) / 1000.0 for x in dropped)
                first_ts = min(x.begin_time for x in dropped) * 1000
                trace_packet_list.append(gen_instant_event_packet(
                    slice_track.uuid, first_ts,
                    f"others: {len(dropped)} waits/segments not drawn "
                    f"(p50 {durs[len(durs)//2]:.0f}ms, max {durs[-1]:.0f}ms)"))

            for slice_info in lane_items:
                slice_name: str = slice_info.name if len(slice_info.name) else slice_type
                debug_info = slice_info.debug_info
                begin_time = slice_info.begin_time * 1000
                end_time = slice_info.end_time * 1000
                if end_time > begin_time:
                    trace_packet_list.append(gen_slice_event_packet(
                        slice_track.uuid, begin_time, slice_name,
                        perfetto_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN, debug_info))
                    trace_packet_list.append(gen_slice_event_packet(
                        slice_track.uuid, end_time, slice_name,
                        perfetto_pb2.TrackEvent.Type.TYPE_SLICE_END))
                else:                                     # 零宽的 .start/.end 标记 → instant
                    trace_packet_list.append(gen_instant_event_packet(
                        slice_track.uuid, begin_time, slice_name))

    thread_info_map = raw_content.thread_info_map
    
    for method_tree in method_tree_list:
        tid = method_tree.tid
        thread_info = thread_info_map.get(tid)
        name = ""
        
        if method_tree.main_thread:
            name = "main"
        elif thread_info:
            name = thread_info.name

        full_name = f"Callstack: Thread {name}"
        thread_packet = gen_thread_packet(auto_increase.get(), process.pid, tid, full_name)
        trace_packet_list.append(thread_packet)
        thread_track = thread_packet.track_descriptor
  
        for method_node in method_tree.root.children:
            method_tree_to_trace(trace_packet_list, thread_track, method_tree, method_node, addr_symbol_map)

    trace.packet.extend(trace_packet_list)

    return trace
