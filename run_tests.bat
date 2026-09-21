@echo off
cd /d "%~dp0"
echo ===== Sales Agent test suite =====
python tests\test_message_splitter.py
python tests\test_backup.py
python tests\test_self_check.py
python tests\test_enterprise.py
python tests\test_leads.py
python tests\test_solda_modules.py
python tests\test_concurrency.py
python tests\test_business_modules.py
python tests\test_personal_wechat.py
echo ===== All tests passed =====
