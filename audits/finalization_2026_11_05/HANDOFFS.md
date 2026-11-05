# Engineering handoffs - baseline3c41747

Các lỗi dưới đây tái hiện bằng runtime thật trên localhost. Test tại Role4 không sửa production. Ưu tiên P1 = chặn tuyên bố reliability/integrity hoàn chỉnh; P2 = cần xử lý hoặc nêu giới hạn rõ. Historical issues được đánh giá lại, không tự giữ trạng thái cũ.

## A1-01 / P1 / protected client.py owner - upload staging collision

Repro: `python -m unittest discover -s tests -p test_role4_delivery.py -v`. Hai HTTPrequests gửi `shared.txt` cho Bob/Cara. Gate ở đầu public send_file của Bob cho phép request Cara ghi staging trước; đây là thread schedule hợp lệ, không mock network. Cả receiver completed nhưng Bob nhận bytes của Cara. SHA mong muốn Bob `9d9dafab76801a5e2265ecc680a3b56de56effcb7a7856af06835c862110dddf`; thực tế `bf80cbf1c34659bba2795f8d5ab8b6e17090f0a5291684305627b31dda9f86d8`.

Root cause: `UIHandler.do_POST` ghi `.upload_temp / Path(name).name` trước tạo worker; request độc lập chia cùng đường dẫn. Một nút disabled hoặc mỗi clientcwd riêng không chặn nhiều tab của cùng client. Fernet/hash tính sau ghi đè nên không giúp phát hiện sai file gốc.

Minimal change proposal: mỗi request có directory riêng; giữ basename trong directory đó để không đổi filename receiver. Worker sở hữu path, đọc snapshot không bị request khác ghi, finally cleanup sau khi reader xong. Trả operation id và expose error trướcrecord choUI nếu có thể. Không thay protocol để chữa staging.

Acceptance: regression trên pass với SHA của từng request; repeated samebasename/differentrecipient/cùngcwd khácclient; cleanup không xóa sớm; file/meta APIs cũ vẫn tương thích.

## A1-02 / P1 / Role3 - FILE_RESULT bị mất không có recovery

Repro: `python -m unittest discover -s tests -p test_role4_network.py -k lost_terminal_result -v`. Drop đúng datagram FILE_RESULT đầu tiên ở receiver callback; ACKdata vẫn đến. Receiver completed, bytes đúng; sender vẫn sending100 sau10s. Independent backend test quan sát7s cùng trạng thái, `_pending` rỗng và chat tiếp tục.

Root cause: `_send_worker` kết thúc sau chunkACK, giữ sending nếu chưa nhận result; `_send_file_result` gửi một lần không ACK/retry. Không có completion timer hoặc query. Source cho thấy state có thể treo không giới hạn, test chỉ khẳng định khoảng thời gian đã quan sát.

Proposal: terminal control record theo file_id/peer có TTL; reliable result handshake hoặc sender completion query với retry/boundedtimeout. Completion phải gắn outcome đã verify+commit, không chỉdataack. Cache outcome để duplicate không ghi lại file. Explicit resultloss/error không làm UI chờvôhạn.

Acceptance: drop1result rồi recover done đúnghash; dropmọiresult thì timeoutfailed có nguyênnhân; repeatedfinalcontrol idempotent; cleanup pendingevent/timer; concurrencykhông lẫnpeer/file.

## A1-03 / P1 / Role3 - finalACKloss làm terminal state lùi từ done về failed

Repro: `python -m unittest discover -s tests -p test_role4_network.py -k final_ack_loss -v`. Chỉ dropACKchunk0 của file100byte. FILE_RESULT completed đến và `_on_file_result` setdone; worker vẫn chờ ACKchunk. Khoảng2.54s sau, retryexhaustion ghi `failed: Timeout chunks [0]`. Receiver completed vàbytesđúng. Independent backend history ghi done0.022s rồifailed2.543s.

Root cause: `_on_chunk` return cho ignored retransmit sau incoming đã xóa, không trả completion outcome; `_send_worker` xử lý ACKevent vàterminalresult độc lập. Exception ghiđè terminaldone; `_pending` còn event khi lỗi xảyra trướcunregister.

Proposal: một completionstate machine đồngbộ theo transfer. Successful authenticated terminalresult phải giải quyết/đóng worker phùhợp và là trạngthái bấtbiến; retry sau complete phải được ACK/result từ completedcache. Failure terminal không biến thànhdone vì unknownpacket. Pending cleanup trong finally. Không sửa bằng timeoutlớnhơn hoặc bỏassert ổnđịnh.

Acceptance: finalACKloss pass sauworkerexit, không chỉpollthoángqua; FILE_RESULTloss cũngpass; collision/hashfailure khôngdone; pendingcount về0 saumọi terminalcase.

## A1-04 / P1 requirement gap / Roles1-2 - integrated async streaming/congestion

Inspection: runtimeclient/server/filehandler không import UDPStreamSender/Receiver. Fileprotocol riêng dùng windows/retry; module standalone đã sửa EOF/empty theo fresh backendcontrols nhưng không chứngminh ứngdụng dùng abstraction đó. Không thấy BBR/CUBIC/adaptivepacing trong UDP path.

Đề PDF trang1-2 nêu UDPstreaming, asyncfetchbytes, HoL và BBR/CUBIC; trang2 lại nêu TCPcho file/message; guide7/18 yêu cầu xácnhận. Proposal: chốt transport/congestiondepth với giảngviên, thốngnhất streaminterface và error/backpressure/lifecycle, sau đó tíchhợp theoowner. Không tự lấy TCPdefaultOS làm bằngchứng UDPcongestion.

Acceptance: diagram và runtimecallpath rõ, consumer nhậnbyteasync, concurrentstream không bịchặn khôngcầnthiết, lossordering/completion chứngminh, congestiontest theo phạmvi đãđượcchốt.

## A1-05 / P1 / Roles 1-2 - reserved identity collides with broadcast

Reproduce: `python audits/finalization_2026_11_05/review/verify_review.py`, case `accepted_identity_has_unambiguous_private_address`. A raw peer authenticates as username `*`; Alice calls `send_message('*', marker)`; unrelated Bob receives the marker. This is an ambiguous accepted identity, not a bypass of an explicit wire-level unicast request. On Windows the regular client also fails creating `downloads_*`; raw peer proves the server still admits this name.

Root cause: `server.py` authentication validates nonempty/unique username but not reserved names; `CollaborationClient.send_message` and browser use `*` as broadcast sentinel. Smallest fix: reject reserved/invalid usernames at the authoritative server and validate at startup before creating directories. If allowing all names is intentional, use a typed recipient/mode contract end to end instead of overloading a name. Coordinate API/UI changes before applying.

Acceptance: reserved name rejected with clear error without registry/socket leaks; ordinary Unicode names still work; private message never reaches a third party. Review path-safe mapping for download directories separately.

## A1-06 / P2 / Role 1 client startup - no handshake deadline

Same runner, `client_handshake_has_response_deadline`: isolated listener accepts TCP and reads HELLO but does not answer. The real client process remains blocked after6s and is terminated by the test. Source confirms `client.py:CollaborationClient.__init__` calls `tcp.settimeout(None)` before both `recv_tcp_packet` operations. The5s connect timeout therefore does not bound HELLO/AUTH reads. Observation is >6s; the unbounded conclusion comes from source, not an infinite-duration experiment.

Proposal: bounded HELLO/AUTH receive deadlines, restore blocking mode only after successful auth; close both sockets and partially initialized resources on failure. Test silent/partial HELLO, silent AUTH and delayed valid response; assert bounded exit and useful startup error. Do not alter server auth timeout as a substitute for bounding client waits.

## A1-07 / P2 / Role 3 test owner - stale test contracts

`python -m pytest test_file_client.py test_file_transfer.py -q -p no:cacheprovider`:29pass/6fail,0.26s. Four `send_file(source)` calls lack the now-required recipient; one send callback accepts one argument while metadata ACK supplies packet+recipient; duplicate metadata test expects an exception while receiver now returns the existing transfer idempotently.

Proposal: owner updates signatures/fixtures, asserts idempotent metadata does not reset bytes/state or create duplicate records, and tests metadata mismatches separately. Preserve actual requirements; do not merely change assertions until green. Add pytest as a documented test dependency through owner review. No teammate test was edited in this workflow.

## P2 contract / documentation / release

- `state()` thiếu closed/liveness/operationerrors. UI chỉ HTTPworking + serverunknown; lỗi workertrướcrecord vàunicastoffline cóthể chỉprint. Đềxuất request_id,errorstate,boundedhistory, monotoniclivenesstime có semantics rõ; frontendreuse sau khiapproved.
- SharedREADMEthiếu startserver/client và nhắcpytest chưa khai báo. NewsubmissionREADME cungcấp instructions trongarchive; owner cậpnhậtsharedREADME khireview. Không sửaâmthầm READMEhayrequirements chung.
- Sharedprotocol doc cũmô tảUDPchat nhưngruntimeTCP; báo cáoPDF mới mô tảactualcontract, không thayprotocolspec owner. Design-beforecoding không thể tạo ngược chứngcứ bằng tài liệu mới.
- Fernetkeyshared hardcoded vàplaintextfallback là threatmodel limitation; freshencryptiontest bảo đảm defaultclientcontent encrypted/decryptđúng, không chứngminh identity/authenticationcryptographic.
- LAN, maxsize, soak/slowreader vàfairness chưa hoànthành; cần tăng môi trường vàevidence, không gọi missingtest là implementationfailure.

## Reproduction / evidence index

`final_1.json` và `final_2.json`:23tests,20pass3fail mỗi lần; rawtracebacks đầyđủ. `backend/results.json`: independentloopback tests, states/timing/checksums; `backend/` giữ các lần bổsung riêng. `demo_smoke.json`: happy-pathclient.main realHTTPchat/file/hash. Testnegative đượcgiữ nhưfailure bìnhthường, khôngskip/expectedFailure. Các hợpđồng mới cần upstreamreview trước khiRole4 điều chỉnh UI.
