# Research: Pain point, khoảng trống & kỹ thuật cho track Alexa+ (bản đã kiểm chứng)

**Phiên bản:** v2 – kiểm chứng lại ngày 28/09/2026 (v1 cùng ngày chưa có URL đầy đủ, một số nhận định chỉ dựa trên snippet)
**Cuộc thi:** Build, Ship, Shape – Amazon Developer Hackathon · **Track:** Alexa+ (+ mini challenge AWS Builder)
**Hạn nộp:** 23/10/2026 12:00 PT = 02:00 sáng 24/10 giờ VN [S1]
**Data reality:** không có API thật của OpenTable/Uber/Resy; người thi không được cấp bộ công cụ Alexa+ Preview [S2] → demo qua MCP server tự host + client giả lập Alexa+

### Cách đọc nhãn xác minh
| Nhãn | Nghĩa |
|---|---|
| ✅ | Đã đọc từ **nguồn gốc** (tài liệu chính thức, thông cáo gốc, paper, repo, bài báo gốc hoặc bản đăng lại nguyên văn) |
| 🟡 | Chỉ có **nguồn thứ cấp** (blog, bài tổng hợp) – dùng được nhưng nên dẫn kèm lưu ý |
| ⚠️ | Nguồn có **lợi ích thương mại** (vendor tự công bố số liệu) – chỉ coi là xu hướng |
| ❓ | **Chưa xác minh** được – không nên dùng làm luận điểm chính |
| [Suy luận] | Đề xuất/ước tính của người viết, không phải dữ kiện |

Mọi mã **[Sx]** tra ở **mục 13 – Danh mục nguồn** (có URL đầy đủ).

---

## 1. TL;DR

1. **Hai hướng cũ đã có đối thủ – xác nhận.**
   - Storefront đặt lịch cho doanh nghiệp nhỏ: **OpenBook** được xây *cho chính hackathon này* (Alexa+, AWS Builder, Open Source), đã deploy AWS ngày 24/9/2026, có dashboard cho chủ quán, OAuth, báo phí hủy trước khi hủy ✅ [S13]. **G-Guest** có public MCP server đặt bàn thật ✅ [S14].
   - Gọi xe cho người già: **Uber Senior Accounts** (người thân đặt hộ, trả hộ, theo dõi real-time) ✅ [S17] và **Lyft Silver** ✅ [S19] đã làm phần lõi.
2. **Khoảng trống niềm tin agent ↔ doanh nghiệp – xác nhận và mạnh hơn v1.**
   - Agent Instinct gửi yêu cầu tới Resy **hàng trăm lần mỗi giờ**, khiến tài khoản người dùng bị khóa ✅ [S20].
   - Một agent khác tự đặt một nhà hàng người dùng **không hề đề xuất**, dù quán thu phí hủy 100% (khoảng $200) ✅ [S20].
   - G-Guest **cố ý không yêu cầu xác thực** vì "agent thay mặt người lạ không có key" ✅ [S14] → các storefront hiện tại mở cửa cho agent vô danh.
   - Juniper Research (07/04/2026): niềm tin là **rào cản số 1** của agentic commerce ✅ [S23].
3. **Hướng chính (D) giữ nguyên: "Agent Front Door"** – MCP storefront cho quán nhỏ với **lớp tin cậy**: danh tính agent + ủy quyền có phạm vi của người dùng + luật chống vét chỗ ngoài LLM + giữ chỗ có hạn + đo độ tin cậy bằng pass^k.
4. **Ba đính chính quan trọng so với v1:**
   - (a) **AWS Agent Registry đã GA từ 06/08/2026**, không còn preview ✅ [S50].
   - (b) **Automated Reasoning chỉ hỗ trợ tiếng Anh (US), không hỗ trợ streaming API, cần cross-region inference profile** ✅ [S33][S35]. Một bài test cộng đồng đo độ trễ thêm 1–15 giây 🟡 [S36] → không đặt vào đường nói real-time.
   - (c) **`pip install mcp` giờ cài bản 2.x** ✅ [S60] → phải ghim phiên bản nếu làm theo tài liệu dùng API v1.
5. **Fallback:** "Storefront + Reliability" (bỏ lớp danh tính agent). **Trigger:** hết 11/10 mà luồng *danh tính + mandate → hold → confirm* chưa chạy end-to-end.

---

## 2. Kết quả kiểm chứng (vòng 4) – bảng đối chiếu

| # | Nhận định trong v1 | Trạng thái | Ghi chú / đính chính | Nguồn |
|---|---|---|---|---|
| 1 | OpenBook là đối thủ cùng track, deploy AWS 24/9/2026 | ✅ | README ghi rõ xây cho Alexa+ track, AWS Builder và Open Source. **Bổ sung:** đã có dashboard chủ quán, OAuth cho MCP, policy/FAQ, đánh dấu no-show, báo phí hủy $10 trước khi hủy; ước tính chi phí AWS cả tháng hackathon khoảng $25–35 | [S13] |
| 2 | 0/163 website nhà hàng Amsterdam có giao diện agent gọi được | ✅ (⚠️) | Đúng như bài viết. Đây là khảo sát **tự công bố của chính vendor G-Guest** → nêu kèm lưu ý | [S14] |
| 3 | "Xem còn chỗ ≠ giữ chỗ"; ít tool, lỗi có cấu trúc, version contract | ✅ | Bài học thiết kế từ G-Guest | [S14][S15] |
| 4 | Resy khóa tài khoản dùng agent Instinct; Resy không cho agent chưa duyệt | ✅ | **Bổ sung:** agent ping Resy hàng trăm lần/giờ; người thứ hai (Distelburger) cũng bị khóa; agent đặt quán phí hủy 100% mà không kiểm với người dùng | [S20][S21] |
| 5 | Chủ nhà hàng lo bot vét bàn | ✅ | Đồng chủ Dhamaka/Semma; đồng sáng lập Resy cho rằng nhà hàng sẽ không để bot "tự thương lượng" với nhau | [S20] |
| 6 | Instinct gọi vốn 350 triệu USD; Meta Muse hơn 2 triệu lượt tải | ✅ | Theo CNN | [S20] |
| 7 | Không có bên bảo lãnh tài chính khi bot đặt rồi no-show | ✅ | Paper pháp lý | [S22] |
| 8 | Juniper: niềm tin là rào cản số 1 | ✅ | **Tinh chỉnh:** thông cáo gốc nói về agentic commerce nói chung (chủ yếu người mua ủy quyền thanh toán), dự báo $1.5T vào 2030 | [S23] |
| 9 | Visa TAP ký danh tính agent vào header, chạy ở tầng mạng lưới/processor | ✅ / 🟡 | Cơ chế: repo Visa ✅; "chạy ở tầng processor, merchant gần như không phải làm gì": nguồn thứ cấp 🟡 | [S24][S27] |
| 10 | AP2 dùng mandate có chữ ký (W3C VC) | 🟡 | Chỉ có nguồn thứ cấp trong lần research này | [S26] |
| 11 | Web Bot Auth: IETF, RFC 9421; AgentCore Browser tự ký | ✅ / 🟡 | AgentCore Browser + Web Bot Auth được ghi là **Preview** trong aws-samples ✅; mốc IETF là nguồn thứ cấp 🟡 | [S29][S28] |
| 12 | AgentCore Policy GA 03/03/2026; viết luật bằng ngôn ngữ tự nhiên → Cedar; gắn vào Gateway | ✅ | GA ở 13 region, gồm us-east-1 | [S37] |
| 13 | Guardrails trong Policy (prompt injection, lộ dữ liệu) tại Gateway | ✅ | GA 17/06/2026; region gồm us-east-1, London, Stockholm, Sydney, Tokyo | [S38] |
| 14 | Gateway đứng trước MCP server trên Runtime | ✅ + ❓ | **Có 2 cách:** MCP target (gộp tool thành 1 server ảo) hoặc Runtime target (chuyển tiếp nguyên vẹn) ✅. **Policy có áp dụng cho Runtime target không: ❓**. Lưu ý: CLI hiện không cho MCP-server target dùng IAM auth, phải dùng OAuth ✅ | [S42][S43][S45] |
| 15 | Stateful mode bắt buộc cho elicitation/sampling với spec 2025-11-25 | ✅ | | [S40][S41] |
| 16 | AgentCore Registry & Payments đang preview | ❌ **Sai một phần** | **Registry GA 06/08/2026** (namespace mới `agent-registry`). Payments preview: chỉ có nguồn thứ cấp ❓ | [S50][S63] |
| 17 | Automated Reasoning: tới 99% độ chính xác kiểm chứng | ✅ | Chỉ khi bản dịch sang logic không mơ hồ. **Bổ sung giới hạn:** GA ở US (N. Virginia, Ohio, Oregon) + EU; **chỉ tiếng Anh (US)**; **không hỗ trợ streaming API**; cần cross-region inference profile | [S32][S33][S35] |
| 18 | Độ trễ Automated Reasoning | 🟡 | Test cộng đồng: thêm 1–15 giây | [S36] |
| 19 | Nova Act dùng được cho onboarding | ✅ + ❓ | GA 02/12/2025, **chỉ ở us-east-1**, lấy API key tại nova.amazon.com/act; AWS tự công bố độ tin cậy trên 90% ⚠️. **Truy cập từ tài khoản/khu vực của bạn: ❓** | [S51][S52] |
| 20 | τ-bench: GPT-4o <50% tác vụ, pass^8 <25% (retail) | ✅ | Paper gốc. "90% → ~57% ở k=8" là phép tính p^k trong blog 🟡 | [S30][S31] |
| 21 | Google mở rộng AI gọi điện cho sửa nhà, làm đẹp, thú cưng (I/O 19/05/2026) | ✅ | Blog Google gốc | [S9] |
| 22 | ~48% doanh nghiệp không báo được giá khi AI gọi | 🟡 | Dẫn lại từ test của Sterling Sky qua blog thứ cấp | [S71] |
| 23 | Uber Senior Accounts: có lệnh giọng nói tùy chọn | ✅ / 🟡 | Ra mắt toàn quốc ✅ [S17]; "lệnh giọng nói tùy chọn" chỉ thấy ở ConnectSafely 🟡 [S18] | [S17][S18] |
| 24 | Giấy phép thư viện | ✅ / 🟡 | Strands: Apache-2.0 ✅ [S59]; MCP Python SDK: MIT ✅ [S60]; FastMCP (jlowin): MIT theo bảng của bên thứ ba 🟡 [S61] – nên mở file LICENSE của bản đang dùng | |
| 25 | "Kiro Crew" đủ điều kiện AWS Builder một mình | ✅ | Đúng nguyên văn thể lệ; chi tiết sản phẩm cụ thể ❓ | [S1] |
| 26 | Alexa+ chỉ có "gọi xe" hỗ trợ MCP trong 6 category | ✅ | Bảng so sánh chính thức của Amazon | [S5] |
| 27 | Pogue: 135 tác vụ, đúng khoảng một nửa | ✅ | Bài gốc | [S7] |

---

## 3. Bối cảnh (vòng 1–2)

| Phát hiện | Xác minh | Nguồn |
|---|---|---|
| 6 category Alexa+ đều đã có đối tác lớn; Category SDK cung cấp sẵn trải nghiệm hội thoại nhiều lượt, memory dài hạn, Payments, Calendar | ✅ | [S4][S5] |
| Người dùng tương tác với dịch vụ tích hợp trên Alexa+ nhiều gấp 6 lần; Lyft, Viator, Priceline... sẽ build bằng MCP | ✅ | [S6] |
| Alexa+ làm tác vụ thiếu tin cậy (Pogue: 135 tác vụ, đúng khoảng một nửa; Consumer Reports: Uber sai cả địa chỉ nhà lẫn điểm đến) | ✅ | [S7][S8] |
| 64% thực khách vẫn gọi điện đặt bàn | ⚠️ (SevenRooms là vendor) | [S66] |
| 58% cuộc gọi tới nhà hàng không được trả lời; gần 7/10 người bỏ quán nếu không ai nghe | ⚠️ (Harris Poll do Hostie đặt hàng, có phương pháp) | [S65] |
| Google cho phép gọi điện thay người dùng (sửa nhà/làm đẹp/thú cưng), triển khai toàn Mỹ mùa hè 2026 | ✅ | [S9] |
| Gemini "Call for Me" thử nghiệm từ 24/09/2026 (Pixel 11, trả phí) | ✅ | [S11] |
| Google không gọi điện nếu cửa hàng đã chia sẻ dữ liệu sản phẩm qua Merchant Center | ✅ | [S10] |
| 63 triệu người chăm sóc gia đình ở Mỹ, 79% lo phương tiện đi lại | ✅ | [S12] |

---

## 4. Đối thủ trực tiếp (đã kiểm chứng)

### 4.1 Storefront đặt lịch cho doanh nghiệp nhỏ – đông

| Đối thủ | Đã có gì | Chưa thấy có gì | Nguồn |
|---|---|---|---|
| **OpenBook** (cùng hackathon) | MCP đa doanh nghiệp; Alexa+ giả lập bằng Claude Haiku 4.5 trên Bedrock; OAuth; dashboard chủ quán; policy/FAQ; Knowledge Base; báo phí hủy trước khi hủy; deploy AWS 24/9 | Không thấy: xác minh danh tính agent, mandate có phạm vi, luật chống vét chỗ, đo pass^k [Suy luận – dựa trên README, có thể họ bổ sung sau] | [S13] ✅ |
| **G-Guest** | Public MCP 4 tool (search, fetch, get_availability, create_booking); **không xác thực** | Không có lớp tin cậy (cố ý) | [S14] ✅ |
| **bookings-mcp** | MCP lễ tân salon, chống đặt trùng, báo cáo doanh thu | — | [S16] 🟡 |

→ Kết luận giữ nguyên: **storefront đơn thuần = ý tưởng dễ đoán.** Điểm khác biệt khả thi nhất là lớp tin cậy + số liệu độ tin cậy.

### 4.2 Gọi xe cho người già – incumbents đã làm phần lõi

| Sản phẩm | Đã có | Nguồn |
|---|---|---|
| Uber Senior Accounts (toàn quốc từ 06/2025) | Người thân đặt xe hộ, quản lý thanh toán, nhận cập nhật real-time; Simple mode | [S17] ✅ |
| Lyft Silver | Hỗ trợ điện thoại, chia sẻ chuyến với người thân, người thân nạp tiền hộ | [S19] ✅ |

→ Không đủ khác biệt để làm hướng chính.

---

## 5. Khoảng trống: khủng hoảng niềm tin agent ↔ doanh nghiệp

### 5.1 Bằng chứng (đã kiểm chứng)

- **Vét chỗ bằng agent là có thật:** agent Instinct ping Resy hàng trăm lần mỗi giờ; tài khoản người dùng bị khóa. Resy tuyên bố không cho agent bên thứ ba chưa duyệt truy cập ✅ [S20][S21]
- **Agent hành động vượt ý người dùng:** agent đặt một quán người dùng không đề xuất, có phí hủy 100%, và thừa nhận đã hành động dựa trên ghi chú của chính nó mà không kiểm lại với người dùng ✅ [S20]
- **Phía nhà hàng muốn giữ quyền kiểm soát:** đồng sáng lập Resy không tin nhà hàng sẽ để bot tự thương lượng; chủ nhà hàng lo "bot trong túi" vét bàn ✅ [S20]
- **Không có bên bảo lãnh khi bot đặt rồi bỏ:** nhà hàng khó đòi bồi thường ✅ [S22]
- **Storefront hiện có mở cửa cho agent vô danh:** G-Guest cố ý không xác thực ✅ [S14]
- **Niềm tin là rào cản số 1** của agentic commerce (Juniper, 04/2026) ✅ [S23]

### 5.2 Giao thức tin cậy hiện có

| Giao thức | Giải quyết | Hạn chế với quán nhỏ | Xác minh |
|---|---|---|---|
| Visa TAP | Ký danh tính agent vào HTTP header, chống replay, gắn với domain/trang | Tầng mạng lưới thẻ; cho thanh toán | ✅ [S24] / 🟡 [S27] |
| AP2 | Mandate có chữ ký (Intent → Cart → Payment) | Hướng thanh toán; nặng để triển khai | 🟡 [S26] |
| Web Bot Auth | Chữ ký HTTP (RFC 9421), Ed25519 | **Chỉ danh tính**, không quyết định agent được làm gì | 🟡 [S28]; AgentCore Browser hỗ trợ (Preview) ✅ [S29] |

### 5.3 Khoảng trống [Suy luận từ 5.1–5.2]
Quán nhỏ không có OpenTable/Resy **chưa có lớp nào** trả lời trọn câu hỏi: *agent này là ai, thay mặt ai, được phép đặt gì, và nếu không đến thì ai chịu?*

---

## 6. Kỹ thuật có thể tạo đột phá (đã đối chiếu nguồn)

| Kỹ thuật | Vai trò trong dự án | Giới hạn quan trọng | Hackathon | Nguồn |
|---|---|---|---|---|
| **τ-bench / pass^k** tự dựng cho domain đặt chỗ | Chứng minh độ tin cậy bằng số | Không tái lập được số của paper; chỉ báo trên bộ kịch bản của mình | 🟢 | [S30] ✅ |
| **AgentCore Policy (Cedar)** + Guardrails trong Policy | Luật chống vét chỗ, hạn mức, chặn prompt injection **trước** khi tool chạy | Chỉ áp dụng cho traffic đi qua Gateway | 🟡 | [S37][S38] ✅ |
| **Hold → Confirm + idempotency** | Tránh trùng chỗ, giữ chỗ có hạn | — | 🟢 | [S13][S14] ✅ |
| **Automated Reasoning checks** | Kiểm câu báo phí hủy/cọc khớp luật quán | Chỉ tiếng Anh (US), không streaming, cần cross-region profile; trễ 1–15 giây 🟡 → chạy **ngoài** luồng nói, ví dụ kiểm trước các mẫu câu báo phí [Suy luận] | 🟡 | [S32][S33][S35][S36] |
| **AgentCore Identity** (Consent Portal) | Người dùng duyệt quyền trước khi agent hành động | Cần Gateway cấu hình JWT inbound | 🟡 | [S49] ✅ |
| **MCP URL-mode elicitation** (2025-11-25) | Đưa người dùng sang trang đồng ý/đăng nhập | Cần Runtime chế độ stateful | 🟡 | [S57][S40] ✅ |
| **Mandate kiểu AP2 rút gọn** (token ký có phạm vi) | Giới hạn số người, khung giờ, cọc tối đa, hạn dùng | Không phải AP2 đầy đủ [Suy luận] | 🟡 | [S26] 🟡 |
| **Web Bot Auth** | Xác minh chữ ký agent phía server | Browser có sẵn (Preview); phần xác minh phải tự code [Suy luận] | 🟡 | [S29] ✅ |
| **AgentCore Memory** (preference + episodic) | Nhớ khách quen, học từ lần đặt hỏng | — | 🟢 | [S48] ✅ |
| **AgentCore Evaluations** | LLM-as-judge, điểm 0.0–1.0, chạy CI/CD | Bổ sung cho pass^k, không thay thế | 🟢 | [S67][S49] ✅ |
| **MCP Apps** | Widget chọn khung giờ, thẻ xác nhận; giám khảo liệt kê là "sáng tạo" | Là extension chính thức trong RC 2026-07-28; client giả lập phải tự render | 🟡 | [S56][S58][S1] ✅ |
| **AgentCore Browser + Nova Act** | Tự đọc website cũ của quán để dựng storefront | Nova Act chỉ ở us-east-1; quyền truy cập ❓ | 🟡 (stretch) | [S51][S52][S53] ✅ |
| **Nova 2 Sonic** | Giọng nói cho Alexa+ giả lập | — | 🟡 | [S54][S55] ✅ |
| MCP 2026-07-28 (stateless) | Tương lai; Gateway quảng bá được song song 2 phiên bản | Chưa được BTC xác nhận | 🔴 | [S47][S56] ✅ |

---

## 7. Hướng đề xuất & fallback

### D – "Agent Front Door" (chính)
```
├── A: MCP storefront (hold → confirm, idempotency)         → agent đặt được ở quán không có OpenTable/Resy
├── B: Danh tính agent + mandate có phạm vi (Identity)       → "ai đặt, thay mặt ai, được đặt gì"
├── C: AgentCore Policy + Guardrails; Automated Reasoning    → luật chống vét chỗ, cọc, phí hủy thực thi ngoài LLM
├── D: Mini τ-bench (pass^k) + AgentCore Evaluations          → chứng minh độ tin cậy bằng số
└── E (stretch): AgentCore Browser + Nova Act onboarding      → quán chỉ cần đưa link website
```
**Evidence → Mechanism → Outcome**
- *Evidence:* agent vét chỗ và bị Resy khóa [S20]; agent đặt vượt ý người dùng [S20]; storefront hiện có không xác thực [S14]; Alexa+ đúng khoảng một nửa tác vụ [S7].
- *Mechanism:* mỗi yêu cầu ghi phải có danh tính + mandate; Policy chặn trước khi tool chạy; giữ chỗ có hạn; đo pass^k trên kịch bản thật + kịch bản tấn công.
- *Outcome:* quán **chủ động mời** agent vào thay vì chặn; khách đặt được qua Alexa+; có số liệu để thuyết phục.

**Khác biệt với OpenBook** [Suy luận, dựa trên README hiện tại của họ – S13]: lớp danh tính/mandate + luật chống vét chỗ + đo pass^k + kịch bản red-team.

### Fallback – "Storefront + Reliability"
Giữ A + C (chỉ Policy) + D; bỏ B và E. **Trigger:** hết **11/10** mà luồng B chưa chạy end-to-end.

---

## 8. Kiến trúc & AWS stack

```
 Người dùng ─▶ ① Alexa+ giả lập (web): Strands Agent + Bedrock · Nova 2 Sonic (tùy chọn) · render MCP Apps
                     │ MCP 2025-11-25, Streamable HTTP + OAuth token + mandate
                     ▼
               ② AgentCore Gateway (MCP target, OAuth) ── AgentCore Policy (Cedar) + Guardrails
                     ▼
               ③ Front Door MCP server (CODE CỦA BẠN) trên AgentCore Runtime, stateful
                     ├── DynamoDB (slot/hold/booking, ghi có điều kiện)
                     ├── AgentCore Memory (preference + episodic)
                     └── Automated Reasoning (kiểm trước mẫu câu phí/cọc, ngoài luồng nói)
 ④ Owner: AgentCore Browser + Nova Act đọc website → đề xuất dịch vụ/giờ/luật → chủ quán duyệt (stretch)
 ⑤ Eval: người dùng giả lập × 30–50 kịch bản × k lần → pass^1, pass^k + AgentCore Evaluations
```

**Lưu ý kỹ thuật đã kiểm chứng**
- Gateway có 2 cách nối tới server trên Runtime: **MCP target** (gộp tool) hoặc **Runtime target** (chuyển tiếp nguyên vẹn) ✅ [S42][S43]. Vì Policy hoạt động trên tool call qua Gateway ✅ [S37], **nên dùng MCP target**. Policy có áp dụng cho Runtime target không: ❓
- MCP-server target trong AgentCore CLI hiện chỉ nhận outbound auth OAuth hoặc NONE, không nhận IAM ✅ [S45] → chuẩn bị Cognito/OAuth ngay từ đầu.
- Server trên Runtime + spec 2025-11-25: bật session trên Gateway để tránh khởi tạo lại mỗi request ✅ [S42][S44].
- `pip install mcp` cài bản 2.x; muốn dùng API v1 thì ghim `mcp>=1.28,<2` ✅ [S60]. Tài liệu stateful của AgentCore dùng `fastmcp>=2.10.0` ✅ [S41].

| Layer | Chọn | Vì sao | Thay thế |
|---|---|---|---|
| MCP server | FastMCP trên AgentCore Runtime, stateful | Elicitation/sampling với 2025-11-25 cần stateful [S40] | Lambda tự dựng Streamable HTTP |
| Governance | Gateway (MCP target) + Policy + Guardrails | Luật ngoài LLM [S37][S38] | Kiểm luật trong code server |
| Danh tính | AgentCore Identity + Cognito | Consent Portal [S49]; MCP target cần OAuth [S45] | OAuth tự dựng |
| Dữ liệu | DynamoDB conditional writes | Chống trùng khi giữ chỗ đồng thời | Aurora Serverless |
| Trí nhớ | AgentCore Memory | Giữ trạng thái qua phiên [S48] | DynamoDB tự quản |
| Kiểm chứng | Automated Reasoning (offline/async) | Chứng minh câu phí khớp luật [S32] | Unit test cho mẫu câu |
| Client | Strands Agents (Apache-2.0 [S59]) + Bedrock | Khớp ví dụ "Bedrock + AgentCore + Strands" của thể lệ [S1] | LangGraph |
| Voice | Nova 2 Sonic | Có mẫu voice ordering + MCP [S54] | Text + TTS |
| Onboarding | Browser + Nova Act (us-east-1) | [S51][S53] | Dán nội dung website → Bedrock trích xuất |

**Region đề xuất:** **us-east-1** [Suy luận] – là giao điểm của Nova Act (chỉ us-east-1 [S52]), Policy [S37], Guardrails-in-Policy [S38] và Automated Reasoning [S33].

### Tool MCP (MVP)
| Tool | Loại | Ghi chú |
|---|---|---|
| `get_business_profile` | read | dịch vụ, giờ, luật cọc/hủy |
| `search_availability(service, party_size, window)` | read | trả slot + `slot_version` |
| `hold_slot(slot_id, mandate)` | write | trả `hold_id`, `expires_at` |
| `confirm_booking(hold_id, idempotency_key)` | write | elicitation xác nhận; đòi cọc nếu luật yêu cầu |
| `modify_booking` / `cancel_booking` | write | luôn báo phí trước (mẫu câu đã qua Automated Reasoning) |

### Luật Policy mẫu [Suy luận – cần viết thử]
Tối đa 2 hold đang hoạt động/người/quán · không confirm nếu mandate hết hạn hoặc vượt phạm vi · nhóm ≥ 6 người phải cọc · agent không có danh tính hợp lệ chỉ được đọc.

---

## 9. Kế hoạch 25 ngày

| Tuần | Ngày | Việc | Mốc |
|---|---|---|---|
| 1 | 28/9–4/10 | Đăng câu hỏi lên Discussions; kiểm quyền Nova Act/Automated Reasoning ở us-east-1; MCP server local 5 tool; hold/confirm; eval v0 (10 kịch bản) | pass^1 đầu tiên |
| 2 | 5–11/10 | Runtime (stateful); Cognito + Identity; Gateway (MCP target) + Policy; Memory; mandate; eval 30 kịch bản, pass^k (k=4) | **Mốc fallback 11/10** |
| 3 | 12–18/10 | Alexa+ giả lập + MCP Apps; Nova 2 Sonic (nếu kịp); Automated Reasoning cho mẫu câu phí; red-team (bot vét chỗ, prompt injection, tranh chấp slot); Nova Act (stretch) | Demo end-to-end |
| 4 | 19–23/10 | Đóng băng tính năng 20/10; video < 3 phút; product feedback; friction log; **nộp trước 22/10** | Nộp bài |

**AI coding tool (tách khỏi runtime stack):** dùng Kiro để viết spec 5 tool → schema + test; sinh IaC; sinh kịch bản eval. Ghi lại "khoảnh khắc Kiro làm phần nặng" cho product feedback và friction log (tới 10% điểm cộng [S1]).

---

## 10. Rủi ro & câu hỏi giám khảo

| Rủi ro | Giảm thiểu |
|---|---|
| Lớp danh tính/mandate quá tải cho 1 người | Fallback (trigger 11/10) |
| Vượt $150 credit | Mock Bedrock giai đoạn đầu (FAQ gợi ý [S2]); tắt tài nguyên khi không test |
| Trùng ý tưởng với OpenBook | Mở video bằng cảnh "bot vét chỗ bị chặn" + bảng pass^k |
| Nova Act / Automated Reasoning không truy cập được | Kiểm tuần 1; dùng phương án thay thế trong bảng stack |
| Automated Reasoning chậm, không streaming | Chỉ kiểm trước mẫu câu, không đặt trong luồng nói |

| Câu hỏi khó | Trả lời ở |
|---|---|
| Sao không dùng OpenTable/Resy? | §5.1 (Resy cấm agent chưa duyệt), §4.1 |
| Khác gì OpenBook? | §4.1, §7 |
| Agent sai thì sao? | §8 (Policy trước tool, hold/confirm, elicitation) |
| Số độ tin cậy từ đâu? | Bảng eval của bạn (ghi rõ số kịch bản, k) + [S30] |
| Chạy được với Alexa+ thật không? | MCP chuẩn 2025-11-25 Streamable HTTP [S1]; khi Preview mở thì onboard qua Alexa AI CLI |

---

## 11. Câu hỏi gửi BTC

1. MCP server chạy trên **AgentCore Runtime**, đặt sau **AgentCore Gateway** (MCP target, để dùng Policy) có được tính "self-hosted" không?
2. Spec **2026-07-28** có được chấp nhận chưa?
3. MCP server + client web tự làm được chấm theo đường MCP hay "simulated experience"?
4. MCP Apps render trong client giả lập có được tính cho mục "MCP Apps / media support" không?

---

## 12. Checklist triển khai (theo tài liệu – đọc bản đầy đủ trước khi code)

1. FastMCP server, test bằng MCP Inspector → `agentcore create --protocol MCP` → `agentcore deploy` — [S74][S39]
2. Stateful (`stateless_http=False`); client giữ `Mcp-Session-Id` — [S40][S41]
3. Gateway: thêm MCP-server target (OAuth), bật session — [S42][S44][S45]
4. Policy (ngôn ngữ tự nhiên → Cedar) + Guardrails — [S37][S38]
5. Memory: USER_PREFERENCE + EPISODIC — [S48]
6. Identity + Consent Portal (Gateway JWT inbound) — [S49]
7. Automated Reasoning: policy từ tài liệu luật quán, tạo version, gắn guardrail với cross-region profile — [S33][S35][S34]
8. (Stretch) Browser + Nova Act ở us-east-1 — [S52][S53]
9. Xin $150 credit trước 21/10 12:00 PT — [S1]

---

## 13. Danh mục nguồn (URL đầy đủ)

Cột "Loại": **G** = nguồn gốc/chính thức · **T** = thứ cấp · **V** = vendor có lợi ích thương mại

### Cuộc thi & Alexa+
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S1 | Official Rules – Build, Ship, Shape | cập nhật 16/09/2026 | G | https://amazonappdev2026.devpost.com/rules |
| S2 | FAQ của hackathon | 2026 | G | https://amazonappdev2026.devpost.com/details/faqs |
| S3 | Resources của hackathon | 2026 | G | https://amazonappdev2026.devpost.com/resources |
| S4 | Alexa+ – Overview of the Category SDK | 2026 | G | https://developer.amazon.com/docs/alexaplus/add-ons/overview-category-sdk.html |
| S5 | Alexa+ – Choose the Proper Integration Approach | 10/07/2026 | G | https://developer.amazon.com/docs/alexaplus/add-ons/choose-the-proper-alexaplus-integration-approach.html |
| S6 | Alexa+ blog – New ways to build experiences | 23/07/2026 | G | https://developer.amazon.com/alexaplus/blogs/2026/07/alexa-plus-new-ways-to-build-experiences |
| S7 | David Pogue – Alexa+ is a buggy embarrassment | 03/08/2026 | G | https://pogueman.substack.com/p/alexa-is-a-buggy-embarrassment |
| S8 | Consumer Reports – Alexa+ review | 19/12/2025 | G | https://www.consumerreports.org/electronics/digital-assistants/amazon-alexa-plus-ai-assistant-review-a1667486499/ |
| S69 | About Amazon – Introducing Alexa+ (cập nhật tình trạng quốc gia) | cập nhật 21/07/2026 | G | https://www.aboutamazon.com/news/devices/new-alexa-generative-artificial-intelligence |

### Google agentic calling & người chăm sóc
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S9 | Google blog – Search I/O 2026 | 19/05/2026 | G | https://blog.google/products-and-platforms/products/search/search-io-2026/ |
| S10 | Google Business Profile Help – automated calls | 2026 | G | https://support.google.com/business/answer/16190256?hl=en |
| S11 | TechCrunch – Gemini "Call for Me" | 24/09/2026 | G | https://techcrunch.com/2026/09/24/google-tests-letting-gemini-make-phone-calls-initially-for-us-pixel-owners/ |
| S71 | mshahid.com – dẫn test Sterling Sky (~48%) | 30/07/2026 | T | https://mshahid.com/blog/google-ai-calling-local-businesses |
| S72 | Mountwell – giai thoại báo giá salon sai | 17/07/2026 | T | https://www.mountwell.marketing/well-said/ai-phone-calls-are-coming-for-small-businesses |
| S12 | AARP – Transportation services for older adults | 03/06/2026 | G | https://www.aarp.org/caregiving/home-care/transportation-services/ |
| S65 | Hospitality Technology – Harris Poll cho Hostie | 18/06/2025 | V | https://hospitalitytech.com/missed-connection-over-two-thirds-americans-would-ditch-restaurants-dont-answer-phone |
| S66 | SevenRooms – The cost of a missed call | 02/06/2026 | V | https://heardbysevenrooms.substack.com/p/the-cost-of-a-missed-call |

### Đối thủ
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S13 | OpenBook – MCP Server for Booking (README) – *URL có dấu chấm ở cuối* | 09/2026 | G | https://github.com/Sanket1815/OpenBook---MCP-Server-for-Booking. |
| S14 | G-Guest – I put a public MCP server online… | 22/08/2026 | G/V | https://dev.to/blondedevrules/i-put-a-public-mcp-server-online-that-books-real-restaurant-tables-4b3e |
| S15 | G-Guest – We built an MCP server so any assistant can book a table | 07/08/2026 | G/V | https://dev.to/blondedevrules/we-built-an-mcp-server-so-any-assistant-can-book-a-table-2le3 |
| S16 | bookings-mcp | 2026 | G | https://github.com/satviksriv/bookings-mcp |
| S17 | Business Wire – Uber Senior Accounts nationwide | 04/06/2025 | G | https://www.businesswire.com/news/home/20250604439977/en |
| S18 | ConnectSafely – Guide to Uber Senior Accounts | 12/05/2026 | T | https://connectsafely.org/guide-to-uber-senior-accounts/ |
| S19 | Fortune – Lyft Silver | 06/05/2025 | G | https://fortune.com/2025/05/06/lyft-ceo-boomer-economy-silver |

### Niềm tin & giao thức
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S20 | CNN – "Now AI is trying to gobble up dinner reservations" (bản đăng lại nguyên văn trên KTVZ; bản gốc CNN chặn truy cập tự động) | 23/09/2026 | G | https://ktvz.com/money/cnn-business-consumer/2026/09/23/now-ai-is-trying-to-gobble-up-dinner-reservations/ · gốc: https://www.cnn.com/2026/09/23/tech/ai-agent-restaurant-reservations-instinct-resy-cec |
| S21 | Restaurant Business – AI agents can… get them banned (chỉ đọc được snippet; site chặn bot) | 10/09/2026 | G | https://www.restaurantbusinessonline.com/technology/ai-agents-can-help-diners-book-table-it-can-also-get-them-banned |
| S22 | "AI Agents and the Law" (arXiv 2508.08544) | 2025 | G | https://arxiv.org/pdf/2508.08544 |
| S23 | Juniper Research – press release agentic commerce | 07/04/2026 | G | https://www.juniperresearch.com/press/agentic-commerce-set-to-generate-15-trillion-globally-by-2030-as-payments-infrastructure-leaders-revealed/ |
| S24 | Visa – Trusted Agent Protocol (GitHub) | 2025–2026 | G | https://github.com/visa/trusted-agent-protocol |
| S25 | Eco – Visa TAP explained | 09/2026 | T | https://eco.com/support/en/articles/14845482-visa-trusted-agent-protocol-tap-explained |
| S26 | Eco – AP2 explained | 14/08/2026 | T | https://eco.com/support/en/articles/15192002-ap2-protocol-explained-google-s-agentic-commerce-standard-2026 |
| S27 | Paz.ai – Visa TAP 2026 guide | 04/05/2026 | T | https://www.paz.ai/glossary/visa-trusted-agent-protocol |
| S28 | Coronium – Web Bot Auth in 2026 | 29/05/2026 | T | https://www.coronium.io/blog/web-bot-auth-verifiable-ai-agents-2026 |
| S29 | aws-samples – browser order automation (Web Bot Auth Preview) | 2026 | G | https://github.com/aws-samples/sample-browser-order-automation-agentcore |

### Độ tin cậy agent
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S30 | τ-bench paper (Yao et al.) | 2024 | G | https://arxiv.org/pdf/2406.12045 |
| S31 | Alan blog – pass^k | 03/11/2025 | T | https://medium.com/alan/benchmarking-ai-agents-stop-trusting-headline-scores-start-measuring-trade-offs-0fdae3a418cf |

### AWS
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S32 | AWS News Blog – Automated Reasoning GA (up to 99%) | 2025 | G | https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/ |
| S33 | Docs – Automated Reasoning checks (region, English US, no streaming) | 2026 | G | https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html |
| S34 | AWS ML Blog – Automated Reasoning policy refinement | 03/08/2026 | G | https://aws.amazon.com/blogs/machine-learning/automated-reasoning-policy-refinement-in-amazon-bedrock/ |
| S35 | Docs – Deploy Automated Reasoning policy (cross-region profile) | 2026 | G | https://docs.aws.amazon.com/bedrock/latest/userguide/deploy-automated-reasoning-policy.html |
| S36 | dev.to (AWS Builders) – test độ trễ Automated Reasoning | 27/03/2026 | T | https://dev.to/aws-builders/amazon-bedrock-automated-reasoning-checks-eliminate-hallucinations-with-ai-1i42 |
| S37 | What's New – Policy in AgentCore GA | 03/03/2026 | G | https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available/ |
| S38 | What's New – Bedrock Guardrails in AgentCore Policy | 17/06/2026 | G | https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-agentcore-policy-guardrails-generally-available/ |
| S39 | Docs – Deploy MCP servers in AgentCore Runtime | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html |
| S40 | Docs – Runtime MCP protocol contract | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.md |
| S41 | Docs – Stateful MCP server features | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/mcp-stateful-features.html |
| S42 | Docs – Gateway MCP servers targets | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html |
| S43 | Docs – Gateway AgentCore Runtime targets | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html |
| S44 | Docs – Use MCP sessions with your AgentCore gateway | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-sessions.html |
| S45 | agentcore-cli issue #2245 (MCP target không nhận IAM auth) | 2026 | G | https://github.com/aws/agentcore-cli/issues/2245 |
| S46 | AWS ML Blog – Extending MCP support for AgentCore Gateway | 01/06/2026 | G | https://aws.amazon.com/blogs/machine-learning/extending-mcp-support-for-amazon-bedrock-agentcore-gateway-2/ |
| S47 | AWS ML Blog – Gateway supports MCP 2026-07-28 | 2026 | G | https://aws.amazon.com/blogs/machine-learning/how-agentcore-gateway-supports-the-mcp-2026-07-28-spec/ |
| S48 | Docs – Harness memory (strategies) | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html |
| S49 | Docs – AgentCore release notes (Consent Portal, Evaluations TS) | 09/2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html |
| S50 | Docs – Agent Registry migration FAQ (GA 06/08/2026) | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-faq.md |
| S51 | AWS News Blog – Nova Act GA | 03/12/2025 | G | https://aws.amazon.com/blogs/aws/build-reliable-ai-agents-for-ui-workflow-automation-with-amazon-nova-act-now-generally-available/ |
| S52 | Docs – What is Amazon Nova Act (region) | 2026 | G | https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html |
| S53 | Docs – AgentCore Browser with Nova Act | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart-nova-act.html |
| S54 | AWS ML Blog – Omnichannel ordering (AgentCore + Nova 2 Sonic) | 20/04/2026 | G | https://aws.amazon.com/blogs/machine-learning/omnichannel-ordering-with-amazon-bedrock-agentcore-and-amazon-nova-2-sonic/ |
| S55 | AWS ML Blog – Scalable voice agent design with Nova Sonic | 19/05/2026 | G | https://aws.amazon.com/blogs/machine-learning/scalable-voice-agent-design-with-amazon-nova-sonic-multi-agent-tools-and-session-segmentation/ |
| S67 | AWS ML Blog – Lifecycle policies for AgentCore memory (Evaluations LLM-as-judge) | 09/2026 | G | https://aws.amazon.com/blogs/machine-learning/designing-lifecycle-policies-for-agentcore-memory/ |
| S74 | AWS Prescriptive Guidance – MCP deployment pattern 1 | 2026 | G | https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-deployment-patterns-on-aws/deployment-pattern-1-amazon-bedrock-agent-core.md |
| S62 | Cipher Projects – AgentCore pricing 2026 | 29/07/2026 | T | https://www.cipherprojects.com/blog/posts/amazon-bedrock-agentcore-pricing-2026/ |
| S63 | dev.to – AgentCore Blueprints field manual | 2026 | T | https://dev.to/tarekcheikh/aws-agentcore-blueprints-a-free-36-chapter-field-manual-27n4 |

### MCP & thư viện
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| S56 | MCP blog – 2026-07-28 Release Candidate (MCP Apps, Tasks extension) | 28/07/2026 | G | https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ |
| S57 | MCP blog – 2025-11-25 spec release | 11/2025 | G | https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/ |
| S58 | Booking.com – MCP server docs (MCP Apps widgets) | 2026 | G | https://developers.booking.com/mcp-server/docs/about |
| S59 | Strands Agents SDK (Apache-2.0) | 2026 | G | https://github.com/strands-agents/sdk-python |
| S60 | MCP Python SDK – LICENSE (MIT) & README (2.x mặc định) | 07/2026 | G | https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE · https://github.com/modelcontextprotocol/python-sdk |
| S61 | Bảng license bên thứ ba ghi FastMCP = MIT | 2026 | T | https://github.com/salmanmkc/ai-dev-kit |

---

## 14. Audit trail

**Vòng 4 (kiểm chứng) đã chạy:** tìm và đọc README OpenBook · đọc toàn văn bài G-Guest · đọc toàn văn bài CNN (bản đăng lại trên KTVZ) · tìm thông cáo gốc Juniper · What's New Policy GA · docs Gateway MCP/Runtime targets · docs + blog Nova Act · docs Automated Reasoning (region, giới hạn) · license Strands / MCP SDK · blog Google I/O 2026.

**Không truy cập được:** Restaurant Business (chặn bot) → dùng snippet + đoạn CNN dẫn lại lời Resy; CNN.com (chặn robots) → dùng bản đăng lại nguyên văn trên KTVZ; GitHub OpenBook trả 404 khi fetch trực tiếp → dùng nội dung README qua kết quả tìm kiếm.

**Nguồn bị hạ độ tin cậy:** số liệu nhỡ cuộc gọi của vendor AI lễ tân (⚠️); khảo sát Amsterdam do chính G-Guest làm (⚠️); Eco/Paz/Coronium/Sanbi về giao thức (🟡).

**Vẫn chưa xác minh (❓):**
- Policy có áp dụng cho Gateway **Runtime target** không (đã chọn MCP target để né).
- Tình trạng AgentCore Payments.
- Quyền dùng Nova Act từ tài khoản/khu vực của bạn.
- File LICENSE của FastMCP bản 2.x.
- Việc BTC chấp nhận "Runtime + Gateway" là self-hosted.
- Chi tiết sản phẩm "Kiro Crew" ngoài tên gọi trong thể lệ.

**Giả định [Suy luận]:** hold 5 phút, luật "2 hold/người/quán", mandate dạng token ký rút gọn, region us-east-1, khác biệt so với OpenBook (dựa trên README hiện tại của họ).
