# Kết luận cuối trên upstream84a69a8

**Chưa sẵn sàng tuyên bố hoàn thành toàn bộ đề bài.** Demo cơ bản hoạt động và20 Role4 tests strict đạt hai lần; audit mới vẫn tìm thấy blocker về toàn vẹn file, false success, natural timeout, mã hóa chat, discovery và streaming integration. Chi tiết yêu cầu và bàn giao tại COVERAGE.md và DEFECTS_AND_HANDOFFS.md; báo cáo initial ở BASELINE_C892_REPORT.md.

## Baseline mới và phạm vi thay đổi

Kiểm tra remote cuối audit phát hiện `84a69a8e7a6f81cc176f324181cfb6f8ca3fb900` (`fix role 3 ver2`). Đã fetch, tạo branch `audit/final-project-2026-10-26-latest` trực tiếp từ origin/main, không merge/rebase/rewrite nhánh cũ. Giữ nguyên audit cũ, verification8b91b7b, feature0b42b1f và main local; không push/PR/merge.

Commit mới chỉ đổi quyết định ACK metadata trong file_client.py: `_on_meta()` trả bool, chỉ ACK nếu accepted. Xem `upstream_84a69a8.diff`. Không đổi schema HTTP/UI, chat crypto, discovery, standalone streamer, `_on_chunk` hay expiry. Audit không tự chỉnh production;25 file có sẵn tại baseline84 được hash trước/sau trong environment.json/scope_verification.json.

## Execution mới trên84

| Bộ | Total | Pass | Fail | Error | Skip | Expected failure | Unexpected success | Thời gian |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original normal |20|17|0|0|0|0|3|136.228s|
| Strict lần1 |20|20|0|0|0|0|0|139.399s|
| Strict lần2 |20|20|0|0|0|0|0|136.337s|
| HTTP audit |3|2|1|0|0|0|0|40.819s|
| Metadata ACK unit |2|2|0|0|0|0|0|0.005s|

Artifact: `regression/strict_latest_1.json`, `strict_latest_2.json`, `http/http_latest.json`, `metadata_ack_latest.json`. `execution_latest.json` lưu command và child exit thật. Metadata test dùng metadata hợp lệ và ép receiver callback từ chối: chỉ kiểm tra nhánh mới, không giả thành malformed-packet network test.

- **Valid file/standalone audit84:**10 observations gồm4 positive controls,6 vi phạm invariant;4.337s. `file_streaming/results_latest.json`. Các observations có lặp tái hiện, không phải10 yêu cầu độc lập.
- **24MiB84:**164.156s; receiver timeout74%, sender done100%, không destination. `large_file_latest.json`. Không tiêm packet loss hoặc đổi timeout. Hai lần trênc892 cũng fail163.544s/163.941s; một lần chạy riêng không cạnh tranh network test khác.
- **HTTP8MiB84:**SHA256 đúng, progress thực và terminal state đúng;29.339s. Cùng suite tái hiện upload hai request cùng basename làm Bob nhận bytes của Cara dù cả receiver báo completed.
- **Source equivalence, không giả rerun:** protocol/security đã chạy hai lần ởc892 (mỗi lần8scenarios=1PASS,6FAIL,1OBSERVATION). Đường code gây lỗi không đổi ở84; kết luận vẫn áp dụng qua đối chiếu diff, không ghi đã chạy lại protocol84.
- Existing streamer6nhóm/15input PASS47.647s và existing chat4nhómPASS9.226s là executionc892; các module liên quan không đổi ở84. EOF/empty tests mới chứng minh suite cũ chưa đầy đủ.
- README `python -m pytest -q` thiếu pytest trong venv runtime; không biến thiếu test dependency thành kết luận networking runtime hỏng.

Không cộng suite/group/scenario/rerun thành một số tổng PASS. Giữ cả evidence dương/âm, source baseline và traceback; không sửa existing tests.

## Ba lỗi cũ và sửa mới

| Vấn đề | Kết luận | Không được suy rộng |
|---|---|---|
| Lost final ACK | FIXED ca receiver completed hợp lệ; strict2 lần và HTTP test mới kiểm tra drop, bytes, hai phía terminal | D02/D09 vẫn ACK ignored transfer failed/expired. |
| Receiver timeout→state | FIXED tới state→HTTP→browser thật | Ca nhỏ dùng accelerated cleanup;24MiB kiểm tra natural timeout và bộc lộ lỗi semantics khác. |
| Windows heartbeat reset | Legacy script/watchdog thực đạt trên Windows này | Chưa fault-inject mọi Winsock reset; không claim mọi10054 đã được chứng minh. |
|84a69a8 metadata ACK | Accepted/rejected branch đạt2 unit tests, valid integration hoạt động | Không sửa chunk completion/staging/expiry/crypto/discovery. |

Marker expectedFailure cũ được giữ nguyên source; strict runner bỏ đúng3 marker trong bộ nhớ. Normal latest thực tế có17pass+3unexpectedSuccess, exit1 do marker lỗi thời; không gọi đó là3expectedFailure hoặc20genuine normal passes. `regression/original_latest.json` và `original_latest.log` lưu bằng chứng riêng; baselinec892 cũng cho cùng counts nhưng có thời gian khác.

## Blocker và handoff

1. **D01/D02/D09:** upload trùng tên nhận nhầm nội dung; resend collision và receiver timeout vẫn làm sender done. D01/D02 đã tái hiện lại84, D09 tái hiện24MiB84. Bàn giao protected client bridge/Role3; staging riêng, terminal outcome/completion ACK đúng và expiry theo activity.
2. **D03–D05:** raw TCP đọc được private chat; discovery nguồn tùy ý/schema sai làm routing sai hoặc UDP receive thread chết; snapshot cũ ghi đè trạng thái mới. Role1/2/3 phối hợp; code gây lỗi không đổi84.
3. **D06/R02:** standalone `__END__`7bytes→0,707→700; empty lifecycle chưa complete; runtime chưa dùng UDPStream, chưa chứng minh async byte fetch/BBR-CUBIC. File tích hợp truyền marker đúng; không gán lỗi standalone cho toàn file UI.
4. **D07/D08/R01/R07:** forwarded payload overflow, invalidport; thiếu student technical PDF/READMEstartup; marker lỗi thời và test oracle cần review. Không tự suy ra điểm số hoặc yêu cầu password DB mà đề chưa nêu.

Readiness chỉ xem xét lại sau khi các phản ví dụ hết lỗi mà20 strict vẫn pass, hồ sơ nộp đúng đề, transport/congestion ambiguity được chốt và có thêm LAN/near-limit/soak/slow-peer evidence. Các gaps chưa chạy được ghi rõ trong matrix, không gắn PASS. Không sửa Roles1–3 để làm audit xanh.
