# Final Project Audit Package — 26/10/2026

## Kết luận readiness

**Chưa sẵn sàng tuyên bố hoàn thành toàn bộ đề bài.** Hệ thống có nền tảng hoạt động: handshake/login, registry thông thường, chat broadcast/private,20 client, heartbeat/watchdog, file nhỏ và browser UI đều có bằng chứng thực thi. Tuy nhiên, các lỗi toàn vẹn nội dung, báo thành công sai, timeout file hợp lệ, plaintext chat và discovery không bền vững là blocker đáng kể. Module streaming độc lập có lỗi binary EOF và chưa được tích hợp vào ứng dụng. Hồ sơ nộp bài và mức đáp ứng async streaming/congestion cần hoàn thiện hoặc xác nhận với giảng viên.

Kết luận này không dựa vào số lượng test xanh. **20 test Role4 strict đạt hai lần**, đồng thời audit mới tái hiện lỗi bằng valid application traffic, packet delay và input boundary. Không có production fix, skip hoặc expectedFailure mới để che thất bại.

## Bản đồ package

- [COVERAGE.md](COVERAGE.md): yêu cầu từ đề → bằng chứng/status/giới hạn cho cả10 milestone và các điều kiện bổ sung.
- [DEFECTS_AND_HANDOFFS.md](DEFECTS_AND_HANDOFFS.md):9 defect có reproduction, root cause và đề xuất cho owner;8 risk/gap phân loại riêng.
- [METHODOLOGY.md](METHODOLOGY.md): cách chạy lại, isolation, đánh giá test oracle, môi trường và demo.
- [environment.json](environment.json), [scope_verification.json](scope_verification.json): provenance Git và hash xác nhận source cũ không đổi.
- `requirements/`: trích nguyên đề/slide, hash nguồn, inventory demo và script trích lại.
- `regression/`, `http/`, `protocol_security/`, `file_streaming/`: JSON có actual result, checksum/trạng thái/traceback và script tái lập; logs đi cùng giữ bằng chứng dương và âm.

## Git và phạm vi

Baseline đã fetch: **`c892dc02aa081c10a49cba4709b058ebe9d0d0bd`**, origin/main. Branch mới **`audit/final-project-2026-10-26`**. Giữ nguyên `verify/role4-after-upstream-fixes` ở8b91b7b và feature Role4 ở0b42b1f. Không merge/rebase/push/PR.

So với Role4 ban đầu0b42b1f, tích hợp các commit4340134 (merge Role4),0dac8c3 (Windows reset),91e33e1 (streamer),c892dc0 (Role3). Upstream đổi `client.py`, `server.py`, `file_client.py`, `file_transfer.py`; thêm `udp_streamer.py`, `test_udp_streaming.py`, `test_chat_routing.py`.

**Chỉ tạo artifact/test mới dưới `audits/final_2026_10_26/`.** Không sửa `client.py`, server/protocol/config/file modules, shared README/docs, static UI, hoặc bất kỳ test hiện hữu nào. Mọi file mới thuộc trách nhiệm kiểm thử/tài liệu audit Role4. `.venv` và render PDF trong ignored tmp chỉ là công cụ cục bộ.

## Kết quả thực thi

Đơn vị trong các hàng khác nhau là suite/test group/scenario, **không cộng thành một “tổng test passed”**.

| Phép thử | Total | Pass | Fail | Error | Skip | Expected failure | Unexpected success | Thời gian |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original Role4 (`regression/original.json`) |20|17|0|0|0|0|3|136.141s|
| Strict lần1 (`strict_1.json`) |20|20|0|0|0|0|0|138.378s|
| Strict lần2 (`strict_2.json`) |20|20|0|0|0|0|0|136.426s|
| HTTP audit lần1 |3|2|1|0|0|0|0|41.544s|
| HTTP audit lần2 |3|2|1|0|0|0|0|38.911s|

- Protocol audit hai lần: mỗi lần8 scenarios = **1PASS,6FAIL,1OBSERVATION**,18.447s và18.460s; không coi observation về password là failed rubric.
- Valid-file/standalone audit:10 observations, trong đó6 vi phạm invariant (2 resend collision,3 marker cases,1 empty lifecycle);4 positive controls.4.390s. Không gọi exit1 là lỗi runner: JSON lưu bytes và trạng thái cụ thể.
- HTTP8MiB hai lần: SHA256 đúng, receiver có intermediate progress và completed, sender done;28.735s và27.682s cho từng transfer end-to-end.
- **24MiB, natural timeout, hai lần:** FAIL;163.544s và163.941s. Receiver timeout75%/74%, sender done100%, không file đích. Lần lặp chạy riêng network test, không tiêm loss hoặc thay timeout.
- `test_udp_streaming.py` nguyên bản:6 nhóm/15 transfer inputs báoPASS, exit0,47.647s. Audit marker/empty lifecycle cho thấy suite này chưa bao phủ đủ binary semantics.
- `test_chat_routing.py` nguyên bản:4 nhómPASS, exit0,9.226s; wrapper kiểm tra summary vì script không dùng exit code phản ánh mọi failure.
- README command `.venv/Scripts/python.exe -m pytest -q`: exit1, `No module named pytest`. Đây là khoảng trống tái lập dependency/README, không phải bằng chứng runtime networking hỏng.
- `compileall -q audits/final_2026_10_26` và script trích nguồn chạy thành công. Không thay test source để đạt kết quả.

Lệnh thực tế và exit child nằm trong `execution_summary.json`; lệnh tái lập đầy đủ tại METHODOLOGY. Regression runner gọi đúng unittest discovery pattern `test_role4_*.py` và lưu toàn bộ20 test ids.

## Ba defect trước đây

| Defect | Kết luận trong phạm vi ca hồi quy | Bằng chứng bổ sung / không được suy rộng |
|---|---|---|
| Lost final ACK | FIXED cho transfer hợp lệ đã completed | Strict2 lần; audit_http drop đúng1 ACK, hai phía terminal success, bytes đúng, HTTP đúng. D02/D09 cho thấy ACK ignored sau failed/expired vẫn sai. |
| Receiver timeout không tới state | FIXED propagation | Strict2 lần + HTTP/browser thật hiển thị timeout2 lần. Ca nhỏ dùng cleanup_expired(max_age=0); file24MiB kiểm tra timeout tự nhiên và cho thấy vấn đề semantics khác. |
| Windows heartbeat reset | FIXED đối với legacy script trên máy Windows này | Script giữ heartbeat rồi dừng, watchdog đóng TCP, SUCCESS và exit0 trong cả normal/strict; test silent-peer riêng cũng đạt. Không claim mọi WinError10054 có thể xảy ra đã được tiêm thử. |

Original suite có3 **unexpected successes** vì marker cũ còn trong integrated main, không phải17pass+3expected failure. Audit giữ nguyên source; strict runner vô hiệu hóa marker trong bộ nhớ. Bỏ marker là follow-up Role4 riêng sau review; không ảnh hưởng bằng chứng strict hiện tại.

## Những vấn đề cần ưu tiên

1. **D01/D02/D09 — bảo toàn file và kết quả thật:** upload cùng basename có thể nhận nhầm bytes; resend collision và transfer hết hạn vẫn khiến sender done. Đây là các blocker chức năng chính.
2. **D03–D05 — bảo vệ và độ bền phiên:** chat plaintext; discovery nguồn tùy ý hoặc schema sai có thể làm routing sai/chết UDP thread; snapshot cũ không tự phục hồi.
3. **D06/R02 — đúng mục tiêu streaming:** standalone EOF collision/empty lifecycle; chưa có bằng chứng tích hợp async byte-stream hay BBR/CUBIC theo phạm vi được giảng viên chấp thuận.
4. **D07/D08/R01/R07:** validate payload/port; cập nhật tài liệu protocol, README/startup, student technical PDF; sửa marker/test oracle.

## Điều kiện để có thể đánh giá lại là sẵn sàng

Owner sửa production qua review riêng; chạy lại các phản ví dụ đến khi invariant đúng, đồng thời20 strict vẫn đạt hai lần. Hoàn thiện technical report PDF đúng đề và README tái lập từ venv sạch. Chốt transport/congestion ambiguity với giảng viên; thực hiện LAN nhiều máy, near-limit file và long-running/slow-peer tests trước khi khẳng định reliability rộng hơn localhost demo. Không cần gọi toàn bộ dự án thất bại: phần nền tảng đã có giá trị và đã được chứng minh; nhưng các blocker hiện tại không nên bị che bằng kết quả xanh của bộ20.
