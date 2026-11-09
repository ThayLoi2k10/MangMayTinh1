# Assignment 1: yêu cầu và bằng chứng mới

Nguồn chính: official PDF4 trang, hash trong assignment1_source.txt/provenance; guide giúp nhận diện các điểm mâu thuẫn, không thay rubric. Baseline3c41747. ĐẠT chỉ trong phạm vi đã thử; CHƯA ĐẠT có phản ví dụ/thiếu implementation; CHƯA KIỂM CHỨNG không tự đồng nghĩa code lỗi.

| Requirement | Status | Evidence / giới hạn |
|---|---|---|
| M1 custom packet/types/state diagrams trước coding | MỘT PHẦN | Header !HBBHH và types hiện có; protocol doc có lịch sử trước một số implementation. Technical PDF mới có state/sequence mô tả runtime, không giả đây là bằng chứng trước coding. Shared doc cần đồng bộ với TCPchat/newfile result. |
| M2 TCP handshake + response | MỘT PHẦN | Legacy scripts và client.main thực đều handshake/auth; silent-server probe cho thấy client đọc HELLO không có deadline. |
| M3 login/IP/ports/registry | MỘT PHẦN | Login tên duy nhất, kiểm cổng trong code. Server chấp nhận tên reserved * gây xung đột broadcast; xem A1-05. Không có password database; không suy ra authentication mạnh từ AUTH_OK. |
| Live discovery | MỘT PHẦN |20 client hội tụ trong hai suite; source/schema/seq và periodic refresh đã có trong code. Review xác nhận discovery cơ bản; loss/late snapshot convergence chưa được kiểm lại độc lập trong đợt này. Không claim source check chống mọi spoof LAN. |
| M4 concurrency10-20client | ĐẠT kịch bản thực thi |20clients simultaneous, concurrentbroadcast, crashisolation,3repeatedlogin cycles trong2suite. Không phải20máy hoặc latency/soakbenchmark. |
| M5 broadcast/unicast đúng recipient | MỘT PHẦN | HTTP/runtime/browser và20 client; tên thường gửi private không tới người thứ ba. Tên * có phản ví dụ identity. TCP chat đã hoạt động; streaming requirement riêng bên dưới. |
| M6 UDP files/no corruption | CHƯA ĐẠT tổng thể | File rỗng/text/binary/Unicode/2MiB và browser1MiB có hash/progress.24MiB qua35,952 chunks hoàn tất55.653s, SHA-256 khớp. HTTP staging collision vẫn chuyển nhầm bytes; terminal control còn lỗi. Không suy tới max limit. |
| M7 timeout/brokenpipe/disconnect resilience | MỘT PHẦN | Unexpectedclose, watchdog, serverstop/manualrestart, interruptedfile vàchat survives đạt; mất FILE_RESULT treo sending, lostfinalACK đảo terminaldone→failed. |
| M8 standard encryption | ĐẠT defaultcontent path; security limitation | Freshbackendtest marker absent wire, receiverdecryptđúng; fileFernet thực. Headers/routingmetadata rõ, sharedkey known, rawpeer plaintextfallback và không strongidentity; không tuyên bố mọitraffic/confidentiality trướcinsider. |
| M9 HTTP + client-side JS | ĐẠT runtime cơ bản | client.main phục vụ index thật; noFlask/Django/WebSocket; realbrowser messages/users/fileprogress. |
| UI safe rendering/errors/mobile | ĐẠT assertions đã chạy |textContent, XSSpayload không chạy, malformedstate, timeout/recovery, draftpreservation, boundedDOM, keyboard/mobile. File83MiB validation dùng realFileinRAM; không kiểmtransport83MiB. |
| Network status rõ | MỘT PHẦN |HTTPvàserverunknown riêng; không fake delivered. Backend thiếu verifiedconnection/errorrecords nên cần contractupstream. |
| M10 testing/code quality/local simulation | MỘT PHẦN |23ownedtests chạy2lần,20pass3failure được giữ; independent tests vàdemo commands. Chưa toànreliability, khônggiấu failures. |
| Raw sockets, standardcrypto, no high-level networking | ĐẠT inspection | socket/threading + stdlibhttpserver, vanillaJS; Playwright/reportlab là công cụ test/report riêng. |
| Architecture separation | MỘT PHẦN |Browser→bridge→client→file/network modules có separation; staging/errorlifecycle gắnbridge; independentstreamer chưa được import runtime. |
| Async byte streaming / no needless HoL | CHƯA CHỨNG MINH tích hợp |ThreadedI/O không tự chứng minh asyncconsumerbyteAPI. udp_streamer chưa được runtime dùng; filewholeload vàserver sequentialsendall có risk. Cần runtimeproof + slowreader/concurrentstream tests. |
| Sequence/window/selective retransmit/order | ĐẠT các faultcase nhỏ; chưa toàn bộ |Controlledloss/delay/duplicate/reorder cóbytesexact; finalcontrol reliability fail. Seqwrap/longstream và mọiordering boundary chưa kiểm. |
| BBR/CUBIC congestion support | CHƯA ĐẠT / CẦN CHỐT DEPTH |Fixedwindow/retry không thayBBR/CUBIC. PDFnêu rõ nhưng depth vàtransportmâu thuẫn cần giảngviên chốt; không tự loại yêu cầu. |
| Windows/local/LAN | ĐẠT Windowslocalhost; LANunverified |Edge/Python3.14.4, ports9000/9001. Không chạy2máy, Linux/macOS/firewallNAT test. |
| README install/startserver/connectclients | ĐẠT artifact mới; sharedREADME còn thiếu |submission/assignment1/README.md và archiveREADME có commands; sharedREADME nguyên bản lưutrongpackage đểreview, không sửaprotected. |
| TechnicalPDF architecture/protocol/sequences/reflection | ĐÃ TẠO trong scope |output/pdf/Assignment1_Technical_Report.pdf7pages, sourcebuilder, renderedreview. Reflection tổnghợp evidence cầnteamduyệt; không bịa trải nghiệm/author. |
| ZIP/private repo + source/configs | CANDIDATE có blocker |Package ZIP cómanifest/hashes, excludevenv/downloads/testdata; kiểmCRC + extracted smoke. Khôngpush/PR/changepublicvisibility; khôngclaim candidate là approvedsubmission. |
| Deadline/team setting | CẦN XÁC NHẬN |Đề ghiSunday17/11/2026 vàindividual/pair trong khiteam4; xácnhận LMS/giảngviên. Không tự đặtdeadline/điểmsố. |

Đã sửa Role4 test để không chấp nhận terminaldone thoángqua. Ba failure trong2lần final là cùng nguyênnhân, được independentbackendtest xác nhận. Lỗi disk initial được phân loại environment; không dùng nó để giải thích các failure protocol xác định. Mọi metric/traceback có trong JSON gốc.
