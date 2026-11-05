# Role 4 finalization - 05/11/2026

Baseline tích hợp `3c4174791a7e796a18e6d57c98c03111359cc1a5`. Worktree mới `E:/Downloads/BTL_MMT/finalization_2026_11_05`, branch `finalization/assignment1-assignment2-2026-11-05`. Giữ nguyên working tree gốc có kết quả chưa commit; không reset/discard. Những kết quả tháng10 là lịch sử, không thay execution mới.

## Thay đổi thuộc Role 4

- `static/index.html`: với sending100%, giải thích đang chờ kết quả bên nhận. Không invent endpoint/state, không tự chuyển completed/failed.
- `tests/test_role4_ui.py`: test status mới; dùng browser File thật83MiB để xác minh chặn size, không tạo83MiB trên đĩa đã gần đầy. Không fake size hoặc bỏ assertion về submission count.
- `tests/test_role4_integration.py`: bỏ marker Windows expectedFailure lỗi thời sau execution heartbeat thật thành công. Test gốc teammate không đổi.
- `tests/test_role4_network.py`: final-ACK test đợi worker retry kết thúc, so bytes và fault counter; thêm mất đúng1 FILE_RESULT; giữ assertion đúng kể cả fail. Không thay chunk/retry production.
- `tests/test_role4_delivery.py`: schedule hợp lệ cho hai HTTP upload trùngbasename, khẳng định bytes từng request. Gate chỉ chọn interleaving trước public send_file; HTTP/fileUDP/receiver thực.
- `docs/role4_ui_testing.md`: đánh dấu hồ sơ cũ, dẫn sang kết quả hiện tại.
- `submission/assignment1/`: guide cài/run, demo server+2client.main, PDF builder và package builder. Root README repository vẫn nguyên bản; README của archive là tài liệu mới trong package.
- `output/pdf/Assignment1_Technical_Report.pdf`: architecture diagram, protocol, message/file sequence,1page challenges/solutions, evidence và gaps. Không giả đây là thiết kế viết trước coding hoặc reflection cá nhân được thành viên xác nhận.
- `audits/finalization_2026_11_05/`: runners/log/JSON, independent review/backend evidence, requirement coverage và handoffs.

## Kết quả thực tế

Python3.14.4, Windows, cryptography50.0.2, Playwright1.55.0 và Edge cài sẵn. Interpreter hiện có dùng từ repository gốc nhưng import source từ worktree3c41747 (harness thêm ROOT theo __file__). Root thực thi:

```powershell
E:/Downloads/BTL_MMT/MangMayTinh1/.venv/Scripts/python.exe -X utf8 audits/finalization_2026_11_05/run_role4.py --strict --label initial_strict
E:/Downloads/BTL_MMT/MangMayTinh1/.venv/Scripts/python.exe -X utf8 audits/finalization_2026_11_05/validate.py
```

Runner thứ hai gọi normal suite2 lần rồi demo smoke, lưu command/exitcode trong execution.json. Không loại test hoặc disable marker mới.

| Lần | Total | Pass | Fail | Error | Skip/expectedFailure/unexpectedSuccess | Duration |
|---|---:|---:|---:|---:|---|---:|
| Initial strict, source tests chưa sửa |21|20|0|1|0/0/0|148.105s|
| Final1 |23|20|3|0|0/0/0|156.068s|
| Final2 |23|20|3|0|0/0/0|158.522s|

Initial error là Errno28 khi truncate83MiB fixture; đây là môi trường thật. Sửa fixture giữ nguyên ý nghĩa test. Hai final runs có cùng3 failure xác định: same-name upload, lost FILE_RESULT và finalACK done→failed. Count21 ban đầu vì upstream đã thêm test_meta_ack_allows_transfer_to_complete; thêm2 test mới thành23. Không giữ số20 chỉ để khớp báo cáo cũ.

Demo smoke PASS: server thật +2 client.main, user list, broadcast/private,HTTPfile8192bytes,SHA256. GUI test thật cũng kiểm1MiB file/browser progress và disconnect.20client concurrent và heartbeat/watchdog đã thực hiện, không phải mocktransport. Các fixture DOM chỉ chứng minh presentation/validation.

## Bàn giao và giới hạn

Xem `audits/finalization_2026_11_05/HANDOFFS.md`. Ba failure không sửa được trong ownership vì thuộc protected client.py/file_client.py/file_transfer.py. Frontend chỉ hiển thị trung thực, không giả liveness/terminal state. Không dùng expectedFailure để che.

Để chạy demo: `python submission/assignment1/demo.py` hoặc ba terminal trong guide. Cổng9000/9001 phải trống; harness từ chối port conflicts, chỉ cleanup processes/temp của mình. Không kill process người dùng. File đồng tên trong demo là bug cần sửa, không coi đặt tên khác là giải pháp.

LAN2máy, near100MiB, soak/slowreader, fairness/QoS/congestion chưa chứng minh. Keyshared, thiếuoperationerrors/verifiedserverstate vẫn cần nêu. BBR/CUBIC/asyncstream và actualruntimeintegration phải chốt với Roles1/2/giảng viên. Không tuyên bố assignmentready chỉ vì các ca happy path đạt.
