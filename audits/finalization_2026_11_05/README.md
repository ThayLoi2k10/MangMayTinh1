# Assignment 1 - Final readiness audit, 05/11/2026

**Kết luận: PARTIAL - demo cơ bản hoạt động, chưa đủ điều kiện xác nhận hoàn thành toàn bộ đề.** Ba lỗi file/HTTP có phản ví dụ lặp lại; hai vấn đề identity/startup được kiểm chứng thêm. Không sửa production của Roles 1-3 để làm test xanh.

## Baseline và phạm vi

Đã fetch `origin` và tạo worktree `finalization_2026_11_05`, branch `finalization/assignment1-assignment2-2026-11-05`, từ `3c4174791a7e796a18e6d57c98c03111359cc1a5`. Repository gốc đang có kết quả audit chưa commit được giữ nguyên. Role 4 cũ `0b42b1f` đã nằm trong lịch sử tích hợp, không cherry-pick hoặc merge lại.

Các commit mới được xét: `1c63552` Role 1; `4db6fd0` và `76afde9` file fixes; `87e479a` chat encryption; `11e6291` streamer EOF; `3c41747` config. Bằng chứng lần này gắn với source baseline trên cộng diff Role 4, không dùng kết luận tháng10 thay execution.

Nguồn yêu cầu: PDF Assignment 1 bốn trang và guide slides trong workspace. `COVERAGE.md` ánh xạ toàn bộ milestone, các yêu cầu streaming/congestion và submission. `HANDOFFS.md` cung cấp reproduction, nguyên nhân và acceptance cho owner. PDF kỹ thuật mới nằm ở `output/pdf/Assignment1_Technical_Report.pdf`.

## Execution thực tế

| Lượt | Total | Pass | Fail | Error | Skip / expected / unexpected | Duration |
|---|---:|---:|---:|---:|---|---:|
| Role4 initial strict |21|20|0|1|0 / 0 / 0|148.105s|
| Role4 final 1 |23|20|3|0|0 / 0 / 0|156.068s|
| Role4 final 2 |23|20|3|0|0 / 0 / 0|158.522s|
| Team file tests, pytest |35|29|6|0|0 / 0 / 0|0.26s|

Initial error là `Errno28` khi fixture ghi file83MiB vào ổ gần đầy. Role 4 sửa fixture thành browser File thật cùng kích thước trong RAM, giữ assertion chặn upload. Số21 ban đầu do upstream thêm metadata-ACK test; thêm hai regression test mới thành23. Hai final run không còn expectedFailure; cả ba failure là cùng nguyên nhân xác định.

Các phép thử bổ sung không cộng lẫn vào23 test:

- `backend/results.json`: 6 scenario đã thực thi,4 PASS/2 FAIL. File rỗng/binary/Unicode, collision trên đích được từ chối, default encrypted chat và standalone stream controls đạt. Mất FILE_RESULT và ACK cuối thất bại. Đây là checkpoint sáu ca, không phải báo cáo đã chạy đủ bảy ca của runner.
- `backend/large_file.json`:24MiB PASS,35,952 chunks,55.653s truyền, SHA-256 hai đầu `206320acc7e9ae70b2e614a2a98ef92a9aa6b3b21cb0aa378c5c16c1a4b0e993`. Progress24/52/80% được quan sát; sender done/receiver completed. Timeout config tự nhiên, không kéo dài để né lỗi.
- `backend/large_result.json`: lượt24MiB độc lập trước đó cũng PASS trong54.131s, progress27/55/83% và cùng SHA-256. Hai lượt dùng temporary directory trên C, cleanup dữ liệu của chính test.
- `review/results.json`:4 scenario,2 PASS/2 FAIL. Fragmented HELLO + encrypted chat/discovery và frame65535byte được từ chối an toàn khi forwarding overflow đều đạt; identity `*` và startup deadline không đạt.
- `review/initial_probe_fixture_results.json` giữ lỗi fixture ban đầu: Windows không tạo được thư mục `downloads_*`, và port19000 xung đột khi dùng lại. Runner cuối dùng raw peer cho identity và ephemeral port cho silent listener; không quy hai lỗi fixture đó thành lỗi protocol. Root đã chạy lại runner cuối.
- `demo_smoke.json`: server và hai `client.main()` thực, HTTP UI, users, broadcast/private, file8192byte và SHA-256 PASS.
- `package_smoke.json`: giải nén ZIP vào temporary directory riêng, kiểm mọi hash trong manifest, rồi chạy demo bằng source đã giải nén; PASS trong3.028s. Final archive được build lại sau commit để manifest ghi đúng packaged HEAD; sidecar verification ở workspace chứa hash cuối.
- `timeout_http_ui.json`: receiver expiry → `state()` → real HTTP → Edge DOM hiển thị “Hết thời gian chờ”, không có JS error. Ca này gọi `cleanup_expired(max_age=0)` để kích hoạt expiry; không giả đã chờ đủ timeout tự nhiên.

Trước pytest có một lượt unittest lỗi import vì thiếu pytest; giữ `team_file_tests.txt`. Đã cài pytest9.2.0 và chạy đúng pytest:6 fail gồm4 call thiếu `recipient`,1 callback thiếu đối số recipient,1 expectation duplicate metadata raise đã lỗi thời sau idempotency fix. Đây là **test contract drift**, không tự suy ra sáu lỗi runtime mới. Giữ nguyên test đồng đội và bàn giao cập nhật. Do ổ E xuống dưới3MiB sau cài, đã gỡ đúng năm package mới cài (pytest,pygments,pluggy,iniconfig,colorama), khôi phục tình trạng thiếu pytest ban đầu; không sửa `requirements.txt`.

## Các lỗi quan trọng

| ID | Ưu tiên | Tác động | Owner |
|---|---|---|---|
| A1-01 |P1|Hai HTTP upload cùng basename có thể gửi nhầm bytes; checksum vẫn khớp file đã bị thay|Client HTTP bridge owner|
| A1-02 |P1|Mất một FILE_RESULT: receiver hoàn tất, sender treo sending100|Role3|
| A1-03 |P1|Mất ACK cuối: sender done rồi bị worker ghi đè failed; pending entry còn sót|Role3|
| A1-04 |P1 requirement gap|Chưa chứng minh integrated async byte streaming/BBR/CUBIC theo đề|Roles1-2 + giảng viên|
| A1-05 |P1 privacy boundary|Username `*` được server chấp nhận nhưng API dùng `*` cho broadcast|Roles1-2/client contract|
| A1-06 |P2|Client chờ HELLO vô hạn sau TCP connect, UI chưa kịp khởi động|Role1/client startup|
| A1-07 |P2 reproducibility|Test Role3 chưa theo API/semantics mới; test dependency chưa khai báo|Role3/test owner|

Không phủ nhận phần đã chạy tốt:20 client đồng thời, crash isolation, heartbeat Windows, timeout nhận file truyền lên UI, shutdown/manual restart, loss/reordering cases nhỏ, browser an toàn khi render dữ liệu và mã hóa nội dung mặc định đều có evidence. Standalone EOF recovery đạt nhưng runtime không import streamer này. Authentication hiện là đăng ký tên/session, không password database hoặc identity bảo mật mạnh.

## Lệnh tái lập

Chạy từ worktree, dùng Python có cryptography, Playwright và Edge. Các runner từ chối cổng đang dùng, chỉ cleanup tiến trình/temp do chính chúng tạo. Không chạy đồng thời các test dùng9000/9001.

```powershell
$py = 'E:/Downloads/BTL_MMT/MangMayTinh1/.venv/Scripts/python.exe'
& $py -X utf8 -m unittest discover -s tests -p 'test_role4_*.py' -v
& $py -X utf8 audits/finalization_2026_11_05/run_role4.py --strict --label recheck
& $py -X utf8 audits/finalization_2026_11_05/backend/verify_backend.py --repeat
& $py -X utf8 audits/finalization_2026_11_05/review/verify_review.py
& $py -X utf8 audits/finalization_2026_11_05/supplemental.py
& $py -X utf8 audits/finalization_2026_11_05/verify_timeout_ui.py
& $py -m pip install pytest
& $py -X utf8 -m pytest test_file_client.py test_file_transfer.py -q -p no:cacheprovider
& $py -X utf8 submission/assignment1/demo.py --smoke --output demo-result.json
```

`supplemental.py` dùng TEMP trên C và yêu cầu160MiB trống để truyền24MiB; Windows environment-specific, không làm runtime dependency. Demo guide có ba terminal để nhóm tự trình diễn. Gói ZIP là **submission candidate**, không được gắn nhãn toàn bộ test pass.

## Điều kiện đóng Assignment 1

Sửa A1-01/02/03/05 theo handoff, thêm bounded handshake, cập nhật test của owner; chạy lại toàn suite hai lần và các fault cases. Chốt scope streaming/congestion với giảng viên bằng văn bản, chứng minh runtime hoặc ghi gap được chấp thuận. Chạy LAN hai máy và thử giới hạn file sau khi có đủ disk; kiểm startup từ môi trường mới. Nhóm duyệt reflection, tên thành viên và deadline trước nộp.

Chưa xác minh: soak dài, fairness với slow reader, near-limit file, disk-full có kiểm soát, IPv4 LAN/NAT/firewall đa máy, các OS khác, congestion performance. Không biến missing evidence thành failure; cũng không dùng localhost happy path để tuyên bố đạt mọi điều kiện.
