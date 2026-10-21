#import <Foundation/Foundation.h>
#import <SCLMonitor/SCLMonitor-Swift.h>
#import "BTrace.h"

@interface KIMBTraceBridgeHandler : NSObject <KIMBTraceHandling>
@end

@implementation KIMBTraceBridgeHandler {
    BTrace *_btrace;
    BOOL _installed;
    BOOL _running;
}

+ (instancetype)shared {
    static KIMBTraceBridgeHandler *shared;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        shared = [KIMBTraceBridgeHandler new];
    });
    return shared;
}

- (instancetype)init {
    if (self = [super init]) {
        _btrace = [BTrace shared];
    }
    return self;
}

- (void)installWithConfig:(NSDictionary *)config {
    if (_installed) {
        return;
    }
    NSDictionary *cfg = config ?: @{
        @"enable": @YES,
        @"timeout": @36000,
        @"max_records": @10000,
        @"buffer_size": @8,
        @"plugins": @[
            @{@"name": @"timeseries", @"config": @{}},
            @{@"name": @"timeprofiler", @"config": @{
                @"period": @5,
                @"bg_period": @10,
                @"merge_stack": @NO,
                @"fast_unwind": @YES
            }}
        ]
    };
    [_btrace setupWithConfig:cfg];
    _installed = YES;
}

- (void)run {
    if (!_installed || _running) {
        return;
    }
    [_btrace start];
    _running = YES;
}

- (void)stop {
    if (!_running) {
        return;
    }
    [_btrace stop];
    _running = NO;
}

- (void)beginPhase:(NSString *)name {
    [_btrace beginPhase:name];
}

- (void)endPhase:(NSString *)name {
    [_btrace endPhase:name];
}

- (void)markType:(int64_t)type {
    [_btrace markType:type];
}

- (void)dumpWithTag:(NSString *)tag info:(NSString *)info {
    if (tag.length && info.length) {
        [_btrace dumpWithTag:tag.UTF8String info:info.UTF8String];
    } else if (tag.length) {
        [_btrace dumpWithTag:tag.UTF8String];
    } else {
        [_btrace dump];
    }
}

@end

@interface KIMBTraceBridgeLoader : NSObject
@end

@implementation KIMBTraceBridgeLoader

+ (void)load {
    KIMBTraceMonitor.shared.handler = [KIMBTraceBridgeHandler shared];
}

@end
