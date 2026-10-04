RadioCharts 1.2.18

- cumulative hotfix: includes the 1.2.16 ETM boundary fixes and 1.2.17 Android EMAUS changes
- fixes the upgrade path when 1.2.17 was applied directly over 1.2.15
- Ignoruj resety again uses only RESET gap values returned by Zetta2GO
- does not infer RESET carry from the next playable row (unsafe for long shows / backtimed logs)
- full-hour carry still ignores rows whose start is already 60+ minutes, preventing false +17/+30/+50 minute gaps
- Android versionName 1.2.18 / versionCode 41
