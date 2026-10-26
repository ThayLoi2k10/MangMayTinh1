# Phương pháp, chạy lại và giới hạn

## Git và môi trường

Audit độc lập từ `origin/main=c892dc02aa081c10a49cba4709b058ebe9d0d0bd`, sau fetch/prune. Nhánh `audit/final-project-2026-10-26`; branch verification cũ `8b91b7b` và feature `0b42b1f` vẫn được bảo toàn. Không merge/rebase old feature vì main đã chứa Role4. Không push/PR/merge, không reset hoặc xóa thay đổi người dùng.

Kiểm tra remote cuối audit phát hiện84a69a8. Đã fetch và `git switch -c audit/final-project-2026-10-26-latest origin/main`, mang theo riêng file audit mới chưa commit; không merge, rebase hoặc rewrite branch cũ. `baseline_c892dc0/` giữ snapshots kết quả ban đầu; `*_latest*` phân biệt execution mới. `environment.json` chứa25 hash ở84 trước mọi audit mới; bản c892 nằm trong archive. `run_latest.py` serialize HTTP, strict2 lần và original lần nữa; file audit port29000 chạy process riêng. Các code path không đổi được phân tích bằng diff, không giả là đã rerun.

`environment.json` lưu baseline, Python, OS, dependency versions và SHA-256 của **toàn bộ file tracked trước audit**. `scope_verification.json` kiểm tra lại hashes sau audit. Chỉ tạo file dưới `audits/final_2026_10_26/`; source/test/docs hiện có read-only. `.venv` có thêm công cụ đọc tài liệu, không sửa dependency declarations. Không đưa Python environment vào Git.

Môi trường: Windows/Python3.14.4, cryptography50.0.2, Playwright1.55.0, browser Edge cài sẵn. Các test chạy ở process riêng, temporary working directory, loopback; chỉ terminate subprocess do harness tạo. Bind-probe cổng trước khi start, không kill process để giải phóng port. Ports9000/9001 dành regression/HTTP;19000/19001 dành protocol;29000/29001 dành file. Không chạy hai harness cùng cặp port đồng thời.

Hai agent độc lập điều tra protocol/security và file/streaming; root đối chiếu code, assertion, JSON/log và làm thử nghiệm HTTP/size riêng. Agent requirements hết quota nên root đọc đề trực tiếp. Một nhánh packet-file bất thường bị automatic review từ chối; không lách rejection, chuyển sang valid-file cases. Khi agent hết quota, kết quả ghi ra đĩa được kiểm tra; không coi kết luận chưa có evidence là đã tái hiện.

## Lệnh tái lập

PowerShell tại repository root; không cần nâng quyền. Giữ mọi kết quả cũ nếu muốn so sánh trước khi chạy vì một số runner ghi lại `results.json`.

```powershell
Set-Location E:\Downloads\BTL_MMT\MangMayTinh1
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_role4_*.py" -v
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/run_regression.py --strict --label strict_repeat
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/audit_http.py http_repeat
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/protocol_security/audit_protocol.py
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/file_streaming/functional_audit.py
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/file_streaming/large_file_audit.py large_repeat_new
.\.venv\Scripts\python.exe -X utf8 test_udp_streaming.py
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/audit_metadata_ack.py
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/run_latest.py
```

Thực tế audit gọi cùng unittest discovery bằng `run_regression.py` để lưu metric/traceback JSON. `--strict` chỉ bỏ đúng3 marker trong bộ nhớ, không thay test body hoặc file source, không skip. `run_validation.py` tuần tự chạy HTTP hai lần, strict lần2, original; ghi child exit code thật và UTF-8 combined logs. Lần strict1 được gọi trực tiếp trước đó; PowerShell redirection thêm `NativeCommandError` decoration do unittest ghi stderr, trong khi JSON runner ghi20pass. Không coi wrapper decoration này là failure Python. Các lần còn lại dùng subprocess file redirection để tránh nhầm exit code.

Chuẩn bị môi trường khác nếu thiếu: cài runtime `requirements.txt`, cài **test-only** `playwright==1.55.0` vào venv và dùng Edge (`ROLE4_BROWSER_CHANNEL=msedge`) hoặc cài Chromium theo Playwright và đặt channel phù hợp. `pypdf` chỉ cần nếu chạy lại `requirements/extract_sources.py`; PyMuPDF chỉ dùng đọc/render đề, không cần để chạy network tests. Không thay shared requirements để làm audit xanh.

Các audit negative trả exit1 là kết quả không đạt invariant mong muốn, không được diễn giải thành “runner hỏng” khi JSON có đầy đủ evidence. Nếu exception môi trường/port xuất hiện thì cần phân loại riêng; không đổi assertion.

Metadata ACK unit test dùng metadata hợp lệ tạo bởi OutgoingFile và callback receiver bị ép từ chối để kiểm tra đúng nhánh mới. Đây là unit test quyết định ACK, không phải thử packet malformed qua mạng; không thay thế các integration tests hoặc lách nhánh kiểm tra đã bị chặn.

Hai log ban đầu do PowerShell ghi UTF-16 đã được chuyển UTF-8 để review trong Git; trailing spaces do PowerShell bọc dòng ở log strict1 được bỏ. Không thay test outcomes, nội dung exception hoặc JSON metrics. Log strict1 giữ cả thông báo NativeCommandError của shell để giải thích khác biệt wrapper; strict2 có child exit0 được ghi độc lập.

## Độc lập và độ tin cậy của phép thử

- Original20 và strict20 dùng chính code mới integrated, không dùng checkout verification8b91. Bộ20 có browser fixture tests và real integration; fixture không được tính là chứng minh transport.
- FinalACK test mới chứng minh ACK thực sự bị drop, receiver completed, sender done, bytes đúng, HTTP state đúng. Timeout test mới kiểm tra receiver internal→state→HTTP→browser; chỉ clock boundary được tăng tốc, không bịa120s elapsed.
- HTTP collision dùng Event ở đầu public send_file để chọn một lịch chạy thread hợp lệ. Route HTTP, staging, OutgoingFile, UDP và receiver đều nguyên bản. Đây là chứng minh race tồn tại, không benchmark xác suất.
- File24MiB dùng đúng production timeout và không packet loss injection. Một lần đầu có thể trùng thời gian hoạt động regression; lần lặp chạy riêng network test để phân biệt tải. Không kết luận throughput trên mọi máy từ một số đo.
- Protocol delayed-list dùng snapshot thật từ server và gửi từ chính UDP socket server. Source-check fix đơn lẻ sẽ không khiến test này pass; cần ordering/convergence.
- Standalone streamer existing test `run_transfer` có so sánh bytes, không phải chỉ tin boolean sender. Nhưng empty data có thể bằng rỗng dù lifecycle chưa complete; literal EOF chưa có trong bộ cũ. Audit xác nhận cả bytes và terminal flags.
- Existing chat script `main()` in PASS/FAIL nhưng không trả nonzero trên failed result; cần đọc/assert summary, không chỉ returncode. Các script cũ trong Role4 wrapper kiểm tra text SUCCESS/FAIL bên cạnh exit. Không mặc định tất cả script được pytest collect là có assertion hữu ích.
- Không có source patch để “sửa lỗi cho test pass”. Các failure được giữ, gồm traceback, trạng thái và checksum.

## Demo cơ bản đã có đường chạy được kiểm chứng

Mở ba terminal ở repo root, chạy lần lượt:

```powershell
.\.venv\Scripts\python.exe server.py
.\.venv\Scripts\python.exe client.py --username alice --host 127.0.0.1 --ui-port 8000
.\.venv\Scripts\python.exe client.py --username bob --host 127.0.0.1 --ui-port 8001
```

Browser tại `http://127.0.0.1:8000` và `http://127.0.0.1:8001`. Chọn Mọi người hoặc peer, gửi chat, gửi file tên mới nhỏ; nhận ở `downloads_bob`. Demo này không thay thế audit adversarial và không chứng minh mọi requirement. Đóng demo trước khi chạy harness9000/9001. LAN dùng `--host <server-LAN-IP>` nhưng chưa được xác nhận trên hai máy trong audit.

## Verification gaps còn lại

LAN thật/multiple hosts, non-Windows, slow-reader blocking, soak/resource limits, diskfull, near100MiB/HTTPlimit, congestion/fairness, sequencewrap, extended randomized loss và mọi dạng malformed encrypted file packet chưa được chạy. Không tự ghi PASS. Static risks ở defect register phân biệt rõ với failure có reproduction. Không tuyên bố3expectedFailure cũ đã bao phủ toàn bộ Windows socket errors hoặc mọi terminal transfer state.
