#
# BTrace —— WOA iOS Pod（GitHub fork 的 func_woa 分支）
#
# 仓库：https://github.com/kagurakana/btrace
# 分支：func_woa
#
# 源码沿用上游 btrace-iOS/ 目录布局；本文件位于仓库根目录，
# 让 CocoaPods 的 :git + :branch 依赖能找到 podspec，同时 source_files
# 指到 btrace-iOS/ 下的真实源码，避免复制一份源码。
#
# 更新方式：在 func_woa 分支上修改 btrace-iOS/BTrace 或 BTraceDebug 后提交。

Pod::Spec.new do |s|
  s.name             = 'BTrace'
  s.version          = '0.1.0'
  s.summary          = 'BTrace iOS 采样 profiler（callstack 采样 + 阶段标注 + Debug 采集端）。'

  s.description      = <<-DESC
BTrace 的 iOS 端源码（WOA fork）。Core 提供进程内 callstack 采样与 TimeSeries 阶段标注
（beginPhase/endPhase）；Debug 提供 App 内 GCDWebServer 控制面（/record/start、
/record/stop、/config/upload），供自动化按用例开关录制。
                       DESC

  s.homepage         = 'https://github.com/kagurakana/btrace'
  s.license          = { :type => 'MIT', :file => 'LICENSE' }
  s.author           = { 'bytedance' => '' }
  s.source           = { :git => 'https://github.com/kagurakana/btrace.git',
                         :branch => 'func_woa' }

  s.ios.deployment_target = '12.0'
  s.default_subspecs = 'Core'

  # ===== Core：SDK 本体（进程内采样 + TimeSeries 阶段标注）=====
  s.subspec 'Core' do |ss|
    ss.source_files        = 'btrace-iOS/BTrace/Classes/**/*.{h,hpp,c,cc,m,mm,cpp}'
    ss.public_header_files = 'btrace-iOS/BTrace/Classes/BTrace/Core/**/*.h',
                             'btrace-iOS/BTrace/Classes/TimeSeriesPlugin/BTraceTimeSeriesPlugin.h',
                             'btrace-iOS/BTrace/Classes/TimeSeriesPlugin/BTraceTimeSeriesData.h'
    ss.pod_target_xcconfig = { 'CLANG_CXX_LANGUAGE_STANDARD' => 'gnu++17' }
    ss.dependency 'fishhook'
    ss.dependency 'Stinger'
    ss.library = 'z', 'sqlite3'
  end

  # ===== Debug：App 内 HTTP 控制面（自动化按用例开关录制用）=====
  s.subspec 'Debug' do |d|
    d.source_files         = 'btrace-iOS/BTraceDebug/Debug/**/*.{h,m,mm,c,cc,cpp}'
    d.private_header_files = 'btrace-iOS/BTraceDebug/Debug/**/*.{h}'
    d.dependency 'BTrace/Core'
    d.dependency 'GCDWebServer/Core'
  end
end
