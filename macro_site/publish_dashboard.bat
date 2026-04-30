@echo off
REM Daily auto-publish: rebuild every model forecast that can run unattended,
REM then copy outputs into the public macro-dashboard repo and push.
REM Models that fail are logged and skipped — one bad release won't block the rest.

setlocal
set SRC=C:\Users\chira\PycharmProjects\BloombergFlyProject
set DST=C:\Users\chira\PycharmProjects\macro-dashboard
set LOG=%SRC%\macro_site\publish.log
set PY=python

echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo Run started %DATE% %TIME%                     >> "%LOG%"
echo ============================================ >> "%LOG%"

cd /d "%SRC%" || goto :fail

REM --- Smart orchestrator: only reruns models whose FRED inputs moved.
REM --- Cascades downstream rebuilds (claims update -> NFP + UR also rerun).
echo. >> "%LOG%"
echo --- Orchestrator (dependency-aware reruns) --- >> "%LOG%"
%PY% macro_site\orchestrator.py >> "%LOG%" 2>&1
if errorlevel 1 echo WARN: orchestrator reported failures, continuing to publish step >> "%LOG%"

REM ---- copy fresh outputs into the public repo ----
echo. >> "%LOG%"
echo Copying outputs to %DST% >> "%LOG%"
xcopy /Y /Q "%SRC%\macro_forecasting\output\*.json" "%DST%\macro_forecasting\output\" >> "%LOG%" 2>&1
xcopy /Y /Q "%SRC%\macro_site\track_record.py" "%DST%\macro_site\" >> "%LOG%" 2>&1
xcopy /Y /Q "%SRC%\macro_site\track_record.db" "%DST%\macro_site\" >> "%LOG%" 2>&1
xcopy /Y /Q "%SRC%\cpi_pce_bridge_v2.json" "%DST%\" >> "%LOG%" 2>&1
xcopy /Y /Q "%SRC%\report_table.csv"       "%DST%\" >> "%LOG%" 2>&1
xcopy /Y /Q "%SRC%\adp_run.log"            "%DST%\" >> "%LOG%" 2>&1

REM ---- commit + push (the public repo's GH Action then re-renders) ----
cd /d "%DST%" || goto :fail
git add macro_forecasting/output macro_site/track_record.py macro_site/track_record.db cpi_pce_bridge_v2.json report_table.csv adp_run.log >> "%LOG%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Refresh model outputs %DATE%" >> "%LOG%" 2>&1
    git push >> "%LOG%" 2>&1
    echo PUSHED updates >> "%LOG%"
) else (
    echo No output changes to commit >> "%LOG%"
)

echo Run finished %DATE% %TIME%                    >> "%LOG%"
endlocal
exit /b 0

:fail
echo FAILED: missing source/destination dir >> "%LOG%"
endlocal
exit /b 1
