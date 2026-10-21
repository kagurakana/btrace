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

  # ===== All：Core + Debug + WOA 注入，供 Podfile 按配置整体引入 =====
  s.subspec 'All' do |a|
    a.source_files         = 'btrace-iOS/BTrace/Classes/**/*.{h,hpp,c,cc,m,mm,cpp}',
                             'btrace-iOS/BTraceDebug/Debug/**/*.{h,m,mm,c,cc,cpp}',
                             'btrace-iOS/BTraceWOA/**/*.{h,m,mm}'
    a.public_header_files  = 'btrace-iOS/BTrace/Classes/BTrace/Core/**/*.h',
                             'btrace-iOS/BTrace/Classes/TimeSeriesPlugin/BTraceTimeSeriesPlugin.h',
                             'btrace-iOS/BTrace/Classes/TimeSeriesPlugin/BTraceTimeSeriesData.h'
    a.private_header_files = 'btrace-iOS/BTraceDebug/Debug/**/*.{h}'
    a.pod_target_xcconfig  = { 'CLANG_CXX_LANGUAGE_STANDARD' => 'gnu++17' }
    a.dependency 'fishhook'
    a.dependency 'Stinger'
    a.dependency 'GCDWebServer/Core'
    a.dependency 'SCLMonitor'
    a.library = 'z', 'sqlite3'
  end
end
