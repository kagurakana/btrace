/*
 * Copyright (C) 2025 ByteDance Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

//
//  BTraceDispatchProfilerConfig.h
//  Pods
//
//  Created by ByteDance on 2024/11/6.
//

#ifndef BTraceDispatchProfilerConfig_h
#define BTraceDispatchProfilerConfig_h

#import <Foundation/Foundation.h>
#import "BTracePluginConfig.h"

@interface BTraceDispatchProfilerConfig : BTracePluginConfig

@property(nonatomic, assign, direct) intptr_t period;
@property(nonatomic, assign, direct) intptr_t bg_period;

/// 是否把「异步等待」画成可见的区间（dispatch_after 的延迟、网络请求的耗时）。
/// 默认开：等待类区间的量级很小（dispatch_after + 每个请求各一条），不像 dispatch_async 那样需要采样。
@property(nonatomic, assign, direct) BOOL await_slice;

/// 是否给网络请求打点（swizzle NSURLSessionTask.resume + KVO state）。
/// 默认开；会遍历每个 task 记一条区间，冷启动量级在几十~几百条。
@property(nonatomic, assign, direct) BOOL network;

/// 接口延迟注入（**只用于验证关键路径**，默认空）：@{@"match": URL 子串, @"ms": 延迟毫秒}。
/// 命中的请求会推迟真正 resume 的时刻，等价于给这个接口加固定网络延迟；
/// 用法：{"network_delay": [{"match": "v1/xz_ui/mobile?scope=user", "ms": 1500}]}
/// 判断「某接口是否卡住冷启动」：注入后看冷启动埋点是否等量后移。
@property(nonatomic, strong, direct) NSArray<NSDictionary *> *network_delay;

+ (nonnull instancetype)defaultConfig;

@end

#endif /* BTraceDispatchProfilerConfig_h */

