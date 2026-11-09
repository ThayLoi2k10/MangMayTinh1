# Assignment 1 — Release closure và readiness

Ngày lập hồ sơ: **2026-11-07**. Phạm vi: Assignment 1, toàn bộ bốn vai trò. Các sửa đổi cross-role được người dùng cho phép trong worktree riêng; không push hoặc merge nhánh dùng chung. Báo cáo này phân biệt implementation, bằng chứng thực thi và yêu cầu cần xác nhận, không suy ra mức độ hoàn thành từ số test đơn thuần.

## 1. Nguồn yêu cầu và phiên bản

Nguồn chính là PDF chính thức **Assignment 1 — Distributed Streaming-based Client-Server Collaboration Application**, 4 trang; bản trích xuất để tra cứu nằm tại [assignment1_source.txt](../audits/finalization_2026_11_05/assignment1_source.txt). PDF yêu cầu source, README cài/chạy từng bước và technical report PDF có architecture, protocol, sequence diagram, một trang challenges/solutions.

| Mốc | Giá trị |
|---|---|
| Integrated team baseline | `3c4174791a7e796a18e6d57c98c03111359cc1a5` |
| Trước release closure | `bd191f31f8e47c0801e37d80a8bdfa70f3f7fec4` — gồm audit/finalization và test Role 4 |
| Worktree sửa chữa | `release_closure_2026_11_05` |
| Nhánh riêng | `release/assignment1-closure-2026-11-05` |
| Evidence mới | `audits/release_2026_11_07/` |

Commit HEAD trong log trước khi commit release chỉ là baseline của worktree. Các run mới kiểm tra cả thay đổi chưa commit; không được diễn giải chúng là kết quả của source baseline nguyên trạng. Manifest của gói release phải đối chiếu chính xác bytes được bàn giao.

**Regression gate: PASS — 90/90 test chạy nghiêm ngặt hai lần trên cùng source; không failure/error/skip/expected failure.** Lần thứ hai dùng virtualenv mới. Gói phát hành được kiểm riêng bằng manifest và smoke; không dùng số test để suy ra đã đạt mọi diễn giải của đề. **Readiness toàn đề: PARTIAL** cho tới khi nhóm chốt diễn giải UDP streaming chat/authentication với giảng viên; các phạm vi chưa thực thi được liệt kê rõ bên dưới.

## 2. Kết quả thực thi đã có

| Bài kiểm chứng | Kết quả thực tế | Bằng chứng |
|---|---|---|
| Reproduce baseline trước sửa: staging cùng tên, mất final ACK, mất terminal result | 3 failure trong 17,552 giây; giữ traceback gốc | [baseline_reproduction.txt](../audits/release_2026_11_07/baseline_reproduction.txt) |
| Network + upload collision + async/concurrent transfer targeted | 9 pass, 2 subtest pass trong 23,49 giây | [targeted.txt](../audits/release_2026_11_07/targeted.txt), [JUnit](../audits/release_2026_11_07/targeted.xml) |
| Run toàn suite đầu trong quá trình sửa | 85 test methods: 82 pass, 3 failure, 0 error/skip; 182,062 giây. JUnit đếm thêm 17 successful subtests thành 102. Đây là evidence phát hiện lỗi, không phải run cuối | [full_run_1.json](../audits/release_2026_11_07/full_run_1.json), [log](../audits/release_2026_11_07/full_run_1.txt) |
| Candidate tiếp theo | 89/90 pass; 1 failure do assertion CUBIC dùng cửa sổ cuối thay vì quan sát chuyển trạng thái; 176,431 giây | [candidate_run_2.json](../audits/release_2026_11_07/candidate_run_2.json), [log](../audits/release_2026_11_07/candidate_run_2.txt) |
| Review file: tests team + release file sau sửa | 45 pass trong 4,72 giây | [file_review_after.txt](../audits/release_2026_11_07/file_review_after.txt) |
| Review HTTP/client/session sau sửa | 8 pass và 12 subtest pass trong 9,85 giây | [client_review_tests.txt](../audits/release_2026_11_07/client_review_tests.txt) |
| Protocol/security độc lập | 7 pass, 0 failure, 1 observation; 21,52 giây | [protocol/results.json](../audits/release_2026_11_07/protocol/results.json) |
| File tối đa 100 MiB, real UDP, SHA-256, wrap header seq | PASS, 104857600 byte/149797 chunks; 71,157 giây; sender `done`, receiver `completed`, pending ACK = 0; chat sau truyền vẫn hoạt động | [maximum_file.json](../audits/release_2026_11_07/maximum_file.json) |
| Full suite lần1 | 90 pass, 0 failure/error/skip/xfail; 172,907 giây | [final_run_1.json](../audits/release_2026_11_07/final_run_1.json), [log](../audits/release_2026_11_07/final_run_1.txt) |
| Full suite lần2, virtualenv mới | 90 pass, 0 failure/error/skip/xfail; 169,731 giây; source hash giống lần1 | [final_run_2.json](../audits/release_2026_11_07/final_run_2.json), [log](../audits/release_2026_11_07/final_run_2.txt) |
| Fresh environment | Tạo venv mới, pip install requirements-test.txt; toàn suite chạy thành công bằng interpreter mới | [environment.json](../audits/release_2026_11_07/environment.json), [package versions](../audits/release_2026_11_07/environment_freeze.txt) |
| Legacy scripts sau sửa harness | Chat4/4 nhóm và UDP6/6 nhóm pass hai lần; lần cuối9,202s và18,712s | [legacy.json](../audits/release_2026_11_07/legacy.json), [lần trước](../audits/release_2026_11_07/legacy_first_legacy.json) |
| Extracted package smoke | PASS: 183 file manifest, real client.main, chat broadcast/private, file 8192 byte và SHA-256; 3,141s | [package_smoke.json](../audits/release_2026_11_07/package_smoke.json) |

JUnit có thể đếm cả unittest subtests; không đồng nhất JUnit `tests` với số test methods collected. Báo cáo cuối phải ghi riêng nếu khác nhau, tránh tạo cảm giác tăng test count bằng cách cộng nhiều kiểu đếm.

90 test gồm **23 Role 4 + 32 release regression mới + 35 team file tests**, ngoài ra có21 successful subtests không cộng vào90. Ba regression cũ (`test_upstream_final_ack_loss_should_recover`, `test_upstream_receiver_timeout_should_reach_state`, `test_existing_heartbeat_script`) đều pass hai lần không marker. Chi tiết từng thời gian và fingerprint nằm trong [verification_summary.json](../audits/release_2026_11_07/verification_summary.json). Bộ Role 4 hiện là23 test, không còn chỉ20 test của commit0b42b1f: một upload collision regression và hai terminal-result regressions đã được bổ sung từ đợt finalization.

Bài file 100 MiB dùng source SHA-256 `4cbf988462cc3ba2e10e3aae9f5268546aa79016359fb45be7dd199c073125c0`; received hash trùng. Header bắt đầu tại 65530 nhưng logical chunk index tiếp tục tới 149796. Run ghi 1102 retransmissions và 1031 loss events trong controller: chứng minh completion/recovery trong run này, **không** chứng minh toàn bộ sự kiện đó là physical packet loss hoặc kết luận hiệu năng/fairness chuẩn. Chưa dùng số thời gian một run làm throughput benchmark trên LAN/Internet.

## 3. Ma trận yêu cầu → implementation → evidence

Các mục ĐÃ CHỨNG MINH bên dưới chỉ áp dụng đến điều kiện được mô tả. Hai lượt regression cuối đã đạt; không suy rộng thành chứng nhận mọi mạng/hệ điều hành.

| Yêu cầu chính thức | Implementation và bằng chứng | Trạng thái/phạm vi |
|---|---|---|
| Milestone 1: custom packet/protocol/state diagrams | `protocol.py`, [protocol.md](protocol.md): 8-byte header, opcode, lifecycle; `test_proto.py`, protocol P01/P06 | Format và framing được kiểm chứng. Lịch sử phát triển mới có thể chứng minh phần “trước khi coding”; không hồi tố ngày viết tài liệu |
| Milestone 2: TCP handshake | HELLO/RESP; `test_handshake.py`, P01 fragmented/coalesced frames; total-deadline regression | Đã chứng minh local; handshake thiếu byte hoặc im lặng bị giới hạn thời gian |
| Milestone 3: login, registry/IP/port | Unique-name registration/session ID; `test_auth.py`, P01/P07, reserved identity tests | Đã chứng minh uniqueness/schema/port; **không** có password verification |
| Milestone 4: concurrent clients | Thread per session, bounded writer queue mỗi peer; `test_twenty_clients_crash_isolation_and_repeated_login`, slow-reader queue test | Có kiểm thử thực 20 client, broadcast, process crash và 3 vòng login/logout; đạt cả hai lượt regression cuối |
| Milestone 5: broadcast/private routing | TCP router; test HTTP real chat + third observer; legacy chat routing script | Routing được kiểm qua runtime thật. UDP-chat interpretation còn cần instructor xác nhận |
| Milestone 6: reliable UDP file | Encrypted metadata/chunks, selective ACK/retry, file result/query, SHA-256, no-overwrite publication | Đã chứng minh empty/text/binary/Unicode/multiple transfers trong suite và 100 MiB bằng run riêng; không phải resumable transfer qua restart |
| Milestone 7: network resilience | Heartbeat/watchdog, TCP closure, deadlines, bounded per-peer queue, terminal recovery, close cancellation | Test server shutdown/manual restart, heartbeat timeout, client crash, interruption, lost ACK/result; không tự reconnect |
| Milestone 8: encrypted payload | Fernet chat text và file JSON; team cryptography/hash tests, P02 raw wire inspection | Client chuẩn dùng mã hóa. Key chung/legacy plaintext/control-plane limitations được khai báo, không claim production security |
| Milestone 9: HTTP + client JavaScript | `client.main()` + local `UIHandler` + embedded `static/index.html` | Browser tests kiểm user list, private/broadcast, progress, SHA-256, disconnect, malformed state, injection, mobile/keyboard; không dùng framework |
| Milestone 10: testing/code quality | Tests của team, Role 4, release; runners có raw logs/JUnit/JSON; demo thật | Hai lượt suite cuối pass; archive giải nén đã kiểm manifest và demo thật thành công |
| Async fetch byte stream tách application | `OrderedByteStream.read`, `FileReceiver.get_stream`, per-transfer indices | `test_async_real_file_bytes_and_another_transfer_survive_loss`: đọc byte trước file commit, file khác/chat tiến triển khi stream thiếu chunk; bytes provisional tới EOF |
| Sequencing/ordering/selective retry | Logical per-file indices, pending ACK keyed `(file_id,index)`, standalone EOF/seq | Fault tests loss/delay/duplicate/reorder; maximum file vượt 16-bit wrap; malformed/wrong-peer ACK tests |
| Congestion control BBR/CUBIC | `CubicWindow`, cap64, ssthresh8, ACK-clock/loss response | CUBIC growth/loss/idle tests và real UDP diagnostics; không có BBR hoặc RFC conformance/fairness certification |
| Tách UI/network/data processing | UI→HTTP→client socket→handler/receiver/byte stream | Source inspection và runtime main/HTTP tests; browser không thay network protocol |
| Raw socket, không Flask/Django/WebSocket | `socket`, stdlib `http.server`, vanilla JavaScript, cryptography runtime | Đối chiếu imports/dependencies; runtime không cần cloud/CDN |
| Standard OS, localhost hoặc LAN | Windows localhost test environment | Localhost đáp ứng nhánh môi trường trong đề; LAN hai máy, Linux/macOS chưa chạy trong đợt này |
| Source/README/PDF/ZIP submission | README có install/run/test/demo; protocol diagrams; technical PDF và manifest | Đã có README/protocol, PDF 7 trang render kiểm tra, ZIP manifest và extracted-runtime smoke |

## 4. Các lỗi quan trọng và cơ chế sửa

| Ưu tiên | Lỗi trước sửa / phản ví dụ | Cơ chế khắc phục và regression |
|---|---|---|
| P0 | HTTP upload cùng basename có thể gửi nhầm bytes do staging dùng chung | Temporary directory riêng mỗi request, worker sở hữu cleanup; `test_same_filename_uploads_preserve_request_content` kiểm hai hash độc lập |
| P0 | Receiver hoàn tất nhưng sender nhận ACK/result không đủ rồi tự đổi thành failed | Terminal result bất biến, ràng buộc peer+hash+size; query/replay receiver cache. Test mất final ACK, mất result, mất đồng thời cả hai; mất mọi result phải kết thúc “unconfirmed”, không false done |
| P0 | Receiver timeout chỉ nằm trong nội bộ, API/UI stale | `get_progress()` đọc receiver progress; timeout propagation test qua state và HTTP; interruption không làm chết chat |
| P1 | Control reply tới peer vừa biến mất ném RuntimeError, có thể kết thúc receive loop | Giới hạn bắt lỗi vận chuyển hợp lệ tại send-control; real socket test kiểm receive loop tiếp tục |
| P1 | Window cap bằng slow-start threshold nên healthy path không vào congestion avoidance | Tách cap64 khỏi threshold8; kiểm growth vượt8, loss response và diagnostic real transfer |
| P1 | Socket đã đóng/malformed ACK trong standalone streamer có thể làm lifecycle sai | Đảm bảo error trả failure, validation nguồn/type/status/payload ACK; standalone fault/cancellation tests |
| P1 | HTTP success che lỗi worker; HTTP local còn sống bị diễn giải thành server connected | Bounded operation records, state.connection dựa server response/TCP; lỗi worker hiển thị browser; API failure vô hiệu hóa xác nhận server ở UI |
| P1 | Trang web khác có thể gửi action tới HTTP local | Loopback Host, same-Origin và JSON content-type checks; HTTP origin/rebinding regressions giữ cả trước và sau sửa |
| P1 | Handshake partial/drip hoặc reader chậm có thể giữ tài nguyên/ảnh hưởng người khác | Total monotonic handshake deadline; per-peer bounded outbox/writer; malformed framing và slow-reader tests |
| P1 | UDP snapshots cạnh tranh có thể gắn sequence mới với nội dung cũ | Snapshot/version/emission cùng serialization lock; nguồn/sequence validation; P03/P04/P05 và concurrent discovery tests |
| P2 | File đã tồn tại hoặc xuất hiện ngay trước publish có thể bị ghi đè | SHA-256, `.part` riêng và atomic no-overwrite hard link; late-destination conflict và lost failure-result tests |

Bằng chứng failure trong quá trình phát triển vẫn được giữ để phân biệt sửa cơ chế với việc đổi assertion. Các test cũ phụ thuộc contract đã thay đổi được cập nhật thành assertion mới tương ứng: server shutdown phải cho `disconnected` và users rỗng; không còn yêu cầu giữ snapshot stale hoặc báo “unknown” khi backend đã có tín hiệu xác minh. Không biến known failure thành expectedFailure/skip để đạt gate.

Hai thay đổi về độ tin cậy phép thử cũng được ghi rõ. UI progress test dùng một chunk UDP được giữ tới khi browser quan sát progress thực, rồi giải phóng và kiểm trạng thái/hash; không tăng timeout hoặc tạo progress giả để che transfer nhanh hơn chu kỳ polling. CUBIC test quan sát cửa sổ trong suốt transfer và đòi hỏi từng vượt8: cửa sổ cuối có thể giảm hợp lệ do timeout nên không dùng riêng giá trị cuối để suy ra chưa từng vào congestion avoidance. Test vẫn kiểm giới hạn64 và toàn bộ bytes nhận. Fixture wrong-peer đợi record xuất hiện trước khi truy cập; assertions ACK/result giả bị từ chối không đổi.

Script legacy `test_udp_streaming.py` ban đầu chỉ đạt2/6 nhóm vì harness dừng receiver ngay khi đủ byte, trong khi sender còn chờ ACK bị mất. Log [trước sửa](../audits/release_2026_11_07/legacy_before_test_udp_streaming.py.txt) chứng minh receiver đủ toàn bộ200000byte nhưng sender thiếu ACK. Harness được giữ sống đến khi sender kết thúc, dùng deadline monotonic và báo receiver exception; không đổi tỷ lệ loss, retry hoặc so sánh nội dung. Script này **không nằm trong90 test methods**; nó được sửa sau hai lượt suite và chạy riêng hai lần đều6/6. Production và tất cả90 test methods giữ nguyên bytes; fingerprint khác duy nhất ở file harness legacy, được khai báo trong verification_summary.json thay vì che thay đổi.

## 5. Rủi ro còn lại và phạm vi bàn giao

| Mức | Mục | Đánh giá và hành động |
|---|---|---|
| Cần xác nhận yêu cầu | TCP chat so với câu mục tiêu UDP streaming | Đề có căng thẳng nội tại: mục tiêu nói UDP, phần kỹ thuật cho TCP message/file, milestone6 nói UDP file. Trình bày kiến trúc thật cho giảng viên; nếu yêu cầu mọi chat qua UDP, implementation này chưa đáp ứng nhánh đó |
| Cần xác nhận yêu cầu | “Authentication” | Đề yêu cầu login nhưng không định nghĩa password database. Unique username/session đã có; không khẳng định credential authentication. Nếu giảng viên đòi password verification, cần thêm credential storage/verification và threat model |
| Giới hạn có chủ đích | Shared Fernet key, control discovery không authenticated | Phù hợp demo basic encryption với trust boundary công khai; không dùng trên mạng thù địch hoặc với dữ liệu nhạy cảm. Secure deployment cần key exchange/session binding/control MAC hoặc TLS phù hợp |
| Giới hạn có chủ đích | Không automatic reconnect/resume | Server restart yêu cầu khởi động lại client; transfer phải gửi lại với tên phù hợp. UI báo đúng mất kết nối; đây là recovery được hỗ trợ và đã có test |
| Chưa kiểm chứng | Multi-host LAN, Linux/macOS, VPN/NAT | Chưa có kết quả thực cho các môi trường này. Localhost Windows đã chạy; không chuyển lệnh hướng dẫn thành bằng chứng pass |
| Chưa kiểm chứng | CUBIC fairness/throughput trên Internet, OS-level netem | Fault injection kiểm cơ chế trên real UDP; không thay phép đo bottleneck nhiều luồng hoặc OS-level emulation. Không claim BBR/full RFC9438 |
| Giới hạn tài nguyên | RAM, active capacity, history và result cache | Giữ file theo chunks, có thể8send+8receive; không memory-constant. UI histories hữu hạn; result cache120s/256. Không có biên nhận persistent hoặc exactly-once vĩnh viễn |
| Giới hạn filesystem | Atomic publish cần hard link | Đường Windows được chạy hỗ trợ cơ chế; FAT/exFAT/network filesystem không hỗ trợ phải báo failure. Không đổi sang overwrite fallback chỉ để demo thành công |
| Giới hạn UI | HTTP file nhỏ hơn transport cap | HTTP110MiBJSON≈82,5MiBdata; file API Python/CLI tối đa100MiB. Đây là hai giới hạn khác nhau, không quảng cáo UI upload100MiB |
| Giới hạn kiến trúc | Same-stream ordering và disk commit | Cross-stream gap không chặn nhau ở state machine; một stream vẫn cần byte liên tục và final hash/disk commit đồng bộ. Không hard real-time guarantee |

Không phát hiện một test chưa viết không đồng nghĩa đã có defect; cũng không coi một test pass là bằng chứng toàn bộ threat model. Handoff sau release tập trung những mục trên, với owner phù hợp: Role1/session-security; Role2/UDP-chat interpretation và congestion evaluation; Role3/persistent receipts/disk streaming; Role4/multi-platform/LAN/demo acceptance.

## 6. Lệnh tái lập và điều kiện gate

Từ thư mục source với Python environment đã cài `requirements-test.txt` và browser:

```powershell
python -X utf8 scripts/verify_release.py --label final_run_1
python -X utf8 scripts/verify_release.py --label final_run_2
python -X utf8 scripts/verify_protocol_release.py
python -X utf8 scripts/verify_legacy_release.py
python -X utf8 scripts/verify_large_release.py --mib 100 --output audits/release_2026_11_07/maximum_file.json
python -X utf8 submission/assignment1/demo.py --smoke --output demo-result.json
```

Chạy tuần tự; không dừng process của người dùng để giải phóng cổng. Harness dùng temporary directories và chỉ cleanup process/file của bài thử. Toàn suite gồm assertions team/file, Role4/browser/integration và release adversarial; legacy scripts có runner kiểm cả exit code lẫn dòng PASS/FAIL vì không phải mọi script tự trả mã lỗi đáng tin cậy.

Gate kỹ thuật yêu cầu source cuối pass hai lần toàn suite, zero failure/error/skip/expected failure; three previous regressions pass bình thường; package có manifest và smoke trên source giải nén; PDF render kiểm tra được và claims khớp log. Gate đánh giá môn học vẫn phải ghi rõ diễn giải UDP chat/authentication và các môi trường chưa chứng minh. Nhóm cần duyệt tên thành viên, công lao thực tế và mọi thông tin hành chính trước khi nộp; không tự đặt tên hoặc xác nhận instructor chưa nhận được.

## 7. Phạm vi thay đổi có thể review

User đã mở rộng quyền từ chỉ Role 4 sang production của mọi role **trong worktree riêng** để đóng release. Vì vậy đợt này có sửa Roles 1–3; không được mô tả là chỉ sửa frontend hoặc không chạm protected files. Repository gốc và worktree finalization được giữ nguyên; không push/merge.

| Nhóm file | Mục đích |
|---|---|
| `client.py`, `server.py`, `protocol.py`, `config.py` | Deadline/registry/queue/session, snapshot, state truth, HTTP job staging và origin protection |
| `file_client.py`, `file_transfer.py` | Terminal recovery, peer binding, bounded state, cancellation, integrity và atomic publication |
| `stream_transport.py`, `udp_streamer.py` | Byte stream async độc lập application, CUBIC, ACK/EOF validation và socket lifecycle |
| `static/index.html` | Connection/operation errors, API outage truthfulness và safe presentation |
| `test_file_client.py`, `test_file_transfer.py` | Reconcile public callback/recipient/status contracts; duplicate metadata idempotency và monotonic timeout. Giữ assertion nội dung, integrity và failure |
| `test_udp_streaming.py` | Giữ receiver endpoint sống tới khi sender xong; không cắt mất cơ hội ACK retransmit sau receive completion |
| `tests/test_release_*.py` | Regression mới cho client, file, byte stream/congestion và concurrent streaming |
| `tests/test_role4_integration.py`, `tests/test_role4_ui.py` | Kiểm contract disconnect mới và quan sát progress thật không phụ thuộc tốc độ loopback |
| `requirements-test.txt`, `requirements-report.txt` | Tách dependencies test/PDF khỏi runtime; không thêm framework networking |
| `scripts/*.py` | Runner giữ raw evidence, maximum-size/protocol/legacy checks, tạo report PDF từ kết quả đã chạy |
| `README.md`, `docs/protocol.md`, `docs/release_closure.md`, chú thích lịch sử trong `docs/role4_ui_testing.md` | Cài/chạy/demo, wire contract, requirements/evidence và giới hạn hiện hành |
| `submission/assignment1/README.md`, `submission/assignment1/build_package.py` | Đóng gói source hiện hành cùng hash manifest, không thay root README bằng guide cũ |
| `audits/release_2026_11_07/`, `output/pdf/Assignment1_Release_Report.pdf` | Evidence trước/sau, environment, technical submission report |

Các script/demo/test/historical audit không có diff vẫn được tái sử dụng. `client_handshake.py` và `requirements.txt` không thay đổi. Source Assignment 2 không bị sửa trong nhiệm vụ này.

## 8. Gói bàn giao và verdict cuối

**Regression và demo package: PASS trong phạm vi đã chạy. Readiness toàn đề: PARTIAL.** Không còn lỗi tái hiện trong các test release, nhưng không tự xác nhận cách hiểu UDP streaming chat hoặc password authentication thay giảng viên. LAN nhiều máy, Linux/macOS và congestion fairness WAN chưa được kiểm; các phần này không được quảng cáo là pass.

Báo cáo nộp hiện hành: [Assignment1_Release_Report.pdf](../output/pdf/Assignment1_Release_Report.pdf), 7 trang đã render và kiểm tra trực quan. Source ZIP `Assignment1_Release_2026-11-07.zip` được xuất bên ngoài repository. Candidate đã qua kiểm hash 183 file và smoke trong thư mục giải nén, bằng virtualenv mới: HTTP của hai `client.main()` thật, TCP broadcast/private và UDP file 8192 byte, sender `done`/receiver `completed`/SHA-256 khớp. Final archive được dựng lại sau local commit và kiểm lại; receipt cuối `Assignment1_Release_Verification_2026-11-07.json` nằm cạnh ZIP, ghi đúng commit và SHA-256 của archive được giao. Log candidate trong repository có hash riêng và được giữ để truy vết, không gán hash candidate cho final archive.

Lệnh dựng/kiểm lại (cài optional `requirements-report.txt` để dựng PDF):

```powershell
python scripts/build_release_report.py
python submission/assignment1/build_package.py --output ../Assignment1_Release_2026-11-07.zip
python submission/assignment1/verify_package.py ../Assignment1_Release_2026-11-07.zip --output ../Assignment1_Release_Verification_2026-11-07.json
```

Dùng `python submission/assignment1/demo.py` để trình diễn có tương tác; hoặc thực hiện ba lệnh server/Alice/Bob ở root README. Không đưa file tải về, virtualenv hoặc dữ liệu thật của người dùng vào ZIP. MANIFEST chứa hash từng file và trạng thái Git lúc đóng gói; toàn bộ thay đổi cross-role có thể review trong local branch.
