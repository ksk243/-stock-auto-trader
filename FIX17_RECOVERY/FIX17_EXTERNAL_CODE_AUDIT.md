# FIX17 EXTERNAL CODE AUDIT

Runtime Pythonに対する静的監査。

- `FIX17_OFFICIAL_FULL_SOURCE.py:42` `from googleapiclient.discovery import build`
- `FIX17_OFFICIAL_FULL_SOURCE.py:43` `from googleapiclient.http import MediaIoBaseDownload`
- `FIX17_OFFICIAL_FULL_SOURCE.py:79` `dl = MediaIoBaseDownload(`
- `FIX17_OFFICIAL_FULL_SOURCE.py:103` `FIX16_EMBEDDED_PARENT_SOURCE = '# ==========================================================================================\n# FIX15 OFFICIAL STANDALONE\n#\n# Parent:\n#   FIX14_OFFICIAL_FULL_SOURCE.py\n#   File ID:\n#       1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk\n#\n# FIX15 addition:\n#   Dynamic Japan`
- `FIX17_RUNTIME_ALL_FUNCTIONS.py:31` `dl = MediaIoBaseDownload(`
- `FIX17_RUNTIME_RESOLVED_FUNCTIONS.py:23` `dl = MediaIoBaseDownload(`
- `FIX17_RUNTIME_RESOLVED_FUNCTIONS.py:965` `downloader = MediaIoBaseDownload(`
- `fix17_long_candidate_bridge.py:48` `ns = runpy.run_path(`
- `paper_trader.py:398` `ns = runpy.run_path(`
- `paper_trader.py:1013` `spec = importlib.util.spec_from_file_location(`
- `paper_trader.py:2542` `ns = runpy.run_path(`
- `paper_trader.py:3091` `ns = runpy.run_path(`
- `paper_trader.py:3845` `spec = importlib.util.spec_from_file_location(`
- `paper_trader_before_contract_gate.py:396` `ns = runpy.run_path(`
- `paper_trader_before_contract_gate.py:1135` `spec = importlib.util.spec_from_file_location(`
- `paper_trader_before_entry_contract.py:397` `ns = runpy.run_path(`
- `paper_trader_before_entry_contract.py:1153` `spec = importlib.util.spec_from_file_location(`