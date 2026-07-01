@echo off
:: CAMARF full pipeline runner — waits for data.py then chains all scripts
:: Usage: run_pipeline.bat <data_py_pid>
setlocal

set PYTHON=C:\Users\RossW\anaconda3\envs\trading\python.exe
set LOG=C:\Users\RossW\Projects\CAMARF\pipeline_runner.log
set PID=%1

cd /d C:\Users\RossW\Projects\CAMARF

echo %DATE% %TIME%  === PIPELINE RUNNER BAT started (waiting for PID %PID%) >> %LOG%

:: Poll until data.py PID is gone
:WAIT_LOOP
tasklist /FI "PID eq %PID%" /NH 2>nul | find "%PID%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo %DATE% %TIME%  data.py still running... >> %LOG%
    timeout /t 30 /nobreak >nul
    goto WAIT_LOOP
)

echo %DATE% %TIME%  data.py done. Starting analysis.py >> %LOG%

:: analysis.py
echo %DATE% %TIME%  === analysis.py === >> %LOG%
%PYTHON% analysis.py >> %LOG% 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo %DATE% %TIME%  analysis.py FAILED >> %LOG%
    goto :EOF
)
echo %DATE% %TIME%  analysis.py OK >> %LOG%

:: backtest IS baseline
echo %DATE% %TIME%  === backtest IS === >> %LOG%
%PYTHON% backtest.py >> %LOG% 2>&1
echo %DATE% %TIME%  backtest IS done >> %LOG%

:: backtest OOS
echo %DATE% %TIME%  === backtest OOS === >> %LOG%
%PYTHON% backtest.py --holdout >> %LOG% 2>&1
echo %DATE% %TIME%  backtest OOS done >> %LOG%

:: STORM variants holdout
for %%F in (--storm-session-edge --storm-session-edge-postopen --storm-mm-exec --storm-coint-frac --storm-all --hub-weight --neg-hedge --risk-parity --pnl-cap) do (
    echo %DATE% %TIME%  === backtest --holdout %%F === >> %LOG%
    %PYTHON% backtest.py --holdout %%F >> %LOG% 2>&1
    echo %DATE% %TIME%  done >> %LOG%
)

:: z=1.5 diagnostic
echo %DATE% %TIME%  === backtest IS --entry-z 1.5 === >> %LOG%
%PYTHON% backtest.py --entry-z 1.5 >> %LOG% 2>&1
echo %DATE% %TIME%  === backtest OOS --entry-z 1.5 === >> %LOG%
%PYTHON% backtest.py --holdout --entry-z 1.5 >> %LOG% 2>&1

:: stats, wfa, distance, sensitivity, report
echo %DATE% %TIME%  === stats.py === >> %LOG%
%PYTHON% stats.py >> %LOG% 2>&1
echo %DATE% %TIME%  === wfa.py === >> %LOG%
%PYTHON% wfa.py >> %LOG% 2>&1
echo %DATE% %TIME%  === distance.py === >> %LOG%
%PYTHON% distance.py >> %LOG% 2>&1
echo %DATE% %TIME%  === sensitivity.py === >> %LOG%
%PYTHON% sensitivity.py >> %LOG% 2>&1
echo %DATE% %TIME%  === report.py === >> %LOG%
%PYTHON% report.py >> %LOG% 2>&1

echo %DATE% %TIME%  === PIPELINE COMPLETE === >> %LOG%
