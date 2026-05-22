@echo off
setlocal
cd /d "%~dp0"

echo === XSD Visualizer - Generate Viewer Files ===
echo.

echo [1/3] Parsing ISO 20022 pain.001.001.09 (original)...
python parser\parse_xsd.py --input xsds\pain.001.001.09.xsd --out viewer\original.json
if errorlevel 1 ( echo FAILED & exit /b 1 )
echo Done.
echo.

echo [2/3] Parsing Georgian revision_0.3...
python parser\parse_xsd.py --input xsds\GEO_pain.001.001.09.revision_0.3.xsd --out viewer\schema-model.json
if errorlevel 1 ( echo FAILED & exit /b 1 )
echo Done.
echo.

echo [3/3] Generating diff...
python parser\diff_xsd.py --old viewer\original.json --new viewer\schema-model.json --out viewer\diff-model.json
if errorlevel 1 ( echo FAILED & exit /b 1 )
echo Done.
echo.

echo === All files generated successfully ===
echo.
echo To view:  cd viewer ^& python -m http.server 8080
echo Then open: http://localhost:8080
echo.
pause
