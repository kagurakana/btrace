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

/// 输出 dispatch_after / 网络请求的等待区间（slice_v2）。
@property(nonatomic, assign, direct) BOOL await_slice;

/// 输出 NSURLSessionTask 请求区间（swizzle -resume + KVO state）。
@property(nonatomic, assign, direct) BOOL network;

/// 按 URL 子串注入固定延迟（毫秒），默认空。
/// 格式：{"network_delay": [{"match": "v1/xz_ui/mobile?scope=user", "ms": 1500}]}
@property(nonatomic, strong, direct) NSArray<NSDictionary *> *network_delay;

+ (nonnull instancetype)defaultConfig;

@end

#endif /* BTraceDispatchProfilerConfig_h */

