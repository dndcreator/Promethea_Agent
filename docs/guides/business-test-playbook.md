# Business Test Playbook

Canonical full checklist:
- [Full Business Test Playbook](../full-business-test-playbook.md)

Quick execution:

```powershell
python tests/run_all_tests.py --suite smoke
python tests/run_all_tests.py --suite core
python tests/run_all_tests.py --suite contracts
python tests/run_all_tests.py --suite business
```

One-step script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite business
```
