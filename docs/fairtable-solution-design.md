# FairTable – Thiết kế giải pháp v2 (tích hợp Agent Front Door)

**Tên tạm:** FairTable – cần kiểm tra trùng thương hiệu trước khi dùng chính thức
**Phiên bản:** **v2 – 28/09/2026**. Gộp phần kỹ thuật "đường ống" của bản *Agent Front Door* (AFD) vào khung sản phẩm FairTable v1.
**Đội:** 1 người, Python · **Mức chi tiết:** thiết kế + diagram (chưa code; riêng các luật Cedar đã chạy thử bằng `cedarpy`)

**File đi kèm:**
- `fairtable-aws-architecture.drawio` – kiến trúc AWS v2
- `fairtable-flows.drawio` – 3 trang: Trust pipeline (2 PEP) · Fair Drop · Eval pipeline (ablation)
- `research-alexa-plus-round3-2026-09.md` – nguồn [S1]–[S74]

**Cách mở:** kéo `.drawio` vào app.diagrams.net. Khối Mermaid hiển thị trên GitHub, VS Code hoặc Obsidian; tất cả đã qua `mermaid.parse` (Mermaid v11).
**Nhãn:** ✅ nguồn gốc · 🟡 thứ cấp · ⚠️ vendor · ❓ chưa xác minh · [Suy luận] đề xuất của người viết · [AFD] ý tưởng lấy từ bản Agent Front Door. Nguồn tra ở mục 16 ([Px]) và file research ([Sx]).

---

## Thay đổi so với v1

| Hạng mục | v1 | v2 | Từ đâu |
|---|---|---|---|
| **Danh tính người dùng khi đi qua Gateway** | Giả định server biết `sub` – **sai**: Gateway gọi server bằng OAuth của chính nó | REQUEST interceptor chép user token sang header; server xác minh lại bằng `joserfc` | [AFD] |
| **Thực thi luật** | Policy ở Gateway + luật có trạng thái viết tay | **2 PEP cùng ngôn ngữ Cedar:** Gateway Policy (G1–G4, không trạng thái) + `cedarpy` trong server (P0 + S1–S4, có trạng thái) | [AFD], đã chạy thử |
| **Mandate** | Token ký KMS, 15 phút cho mỗi booking | **Standing mandate** lưu DynamoDB, duyệt trên điện thoại; vượt phạm vi → **step-up -32042** | [AFD] |
| **Trả hold hết hạn** | TTL DynamoDB – **sai**: TTL xóa trễ tới vài ngày | Hold sweeper mỗi 1 phút + kiểm hạn khi đọc | [AFD] |
| **Ghi dữ liệu** | Ghi có điều kiện + idempotency key | `TransactWriteItems` (slot · bộ đếm · hold · idem · audit); cùng tham số → kết quả cũ, khác tham số → `IDEMPOTENCY_CONFLICT` | [AFD] |
| **Quyền kiểm soát của quán** | Luật R1–R5 | Thêm **S2 – agent share of covers** (trần % chỗ qua agent) | [AFD] |
| **Eval** | 40 kịch bản, 2 simulator | + **ablation A0/A1/A2**, phân loại HAPPY/NEG/ROB/ADV, simulator có tool, C_out, false-block rate, cost/booking, regression gate, nhịp chạy | [AFD] + v1 |
| **Web consent + chủ quán** | Amplify tĩnh | API Gateway + Lambda (FastAPI + Mangum) | [AFD] |
| **Chi phí** | Ước tính | + AWS Budgets cảnh báo $50/$100/$140 | [AFD] |
| **Phiên bản** | FastMCP ≥ 2.14 | FastMCP **3.4.7** (Apache-2.0), mcp **1.30.0**, Strands **1.57.1** – đã kiểm PyPI | [AFD] |
| **Sửa lỗi của AFD** | — | Trigger **V3** cho token M2M + luật G4 có **`has`-guard**; 2 icon draw.io hỏng | Kiểm chứng mới |
| **Giữ từ FairTable** | — | Fair Drop, Standing Watch, Automated Reasoning, onboarding dual-LLM, 2 simulator, ACE, bằng chứng domain | v1 |
| **Bỏ / hạ cấp** | Step Functions cho eval; KMS ký mandate | Eval chạy local + cloud đơn giản; KMS chỉ tạo seed xổ số | [Suy luận] |

---

## 0. TL;DR

1. **Domain:** nhà hàng độc lập. Bằng chứng mạnh nhất (vụ Resy/Instinct 09/2026 [S20], luật New York 2024 [P14]), demo trực quan nhất, và không trùng OpenBook (barbershop) [S13].
2. **Sản phẩm:** một MCP server "cửa trước" cho AI agent với 4 trụ cột:
   - **Standing Mandate + step-up:** ủy quyền có phạm vi, duyệt một lần trên điện thoại.
   - **Trust Pipeline 2 PEP:** hai điểm thực thi luật, cùng viết bằng Cedar.
   - **Fair Drop + Standing Watch:** công bằng khi mở bán, không cần polling.
   - **Proven Reliability:** pass^k, C_out, và ablation A0/A1/A2.
3. **8 tool cho agent** + web cho chủ quán. Không có LLM trong đường quyết định tiền hay chỗ.
4. **Danh tính xuyên suốt:** account linking (OAuth code + PKCE) → token có claim `agent_tier` → interceptor chuyển token người dùng → server xác minh lại → gắn danh tính cho mọi elicitation.
5. **Điểm nhấn khi pitch:** biểu đồ pass^k và số vi phạm của **A0 (cửa hàng mở, kiểu OpenBook/G-Guest)** so với **A1 (FairTable)** – chứng minh lớp tin cậy bằng số.

---

## 1. Chọn domain (giữ từ v1)

| Tiêu chí | Nhà hàng | Salon | Dịch vụ tại nhà |
|---|---|---|---|
| Pain point có báo chí | ✅ Rất mạnh [S20] | 🟡 [S9] | 🟡 [S9] |
| Cơ sở pháp lý | ✅ Luật NY 2024 [P14][P15] | — | — |
| Độ "wow" khi demo | **Cao** (xổ số, bot bị chặn) | Trung bình | Trung bình |
| Trùng đối thủ | Thấp | **Cao (OpenBook)** [S13] | Thấp |
| **Kết luận** | **Chọn** | Tránh | Mở rộng sau |

**Ghi chú pháp lý** [Suy luận, không phải tư vấn pháp lý]: luật NY cấm niêm yết hoặc bán chỗ khi **không có thỏa thuận bằng văn bản với nhà hàng** [P16]. FairTable là kênh do chính nhà hàng mở; agent đặt thay khách, không bán lại chỗ. Trần **agent share (S2)** càng thể hiện rõ việc nhà hàng giữ quyền kiểm soát.

---

## 2. Người dùng & pain point → tính năng

**Chân dung người dùng**
- **Diner (Mỹ)**, dùng Alexa+.
- **Chủ nhà hàng độc lập:** 40–80 chỗ, vài bàn "hot" cuối tuần, sợ bot và no-show.
- **Agent bên thứ ba:** cần một cửa hợp lệ để không bị khóa tài khoản.

| # | Pain point (bằng chứng) | Tính năng | Kỹ thuật lõi |
|---|---|---|---|
| 1 | Agent gửi yêu cầu hàng trăm lần/giờ, bị khóa tài khoản [S20] | Standing Watch + token bucket có `next_step` | MCP Tasks [P17], DynamoDB Streams |
| 2 | Bot vét bàn rồi bán lại [P14]; no-show không ai chịu [S22] | Fair Drop (commit–reveal, 1 phiếu/người) | Mechanism design [P8][P9] |
| 3 | Agent đặt quán phí hủy 100% mà không hỏi lại người dùng [S20] | Standing mandate + **step-up** khi vượt phạm vi | URL elicitation -32042 [P30] |
| 4 | Nhà hàng không muốn để bot "tự thương lượng" [S20] | Luật chủ quán + **trần agent share** | Cedar ở 2 PEP [S37][P39] |
| 5 | Alexa+ đúng khoảng một nửa tác vụ [S7] | pass^k, C_out, ablation | [S30][P35] |
| 6 | 0/163 website nhà hàng Amsterdam cho agent đặt ⚠️ [S14] | MCP storefront + onboarding | FastMCP + AgentCore Browser/Nova Act [S53] |

```mermaid
flowchart LR
  P1["Agent spam hàng trăm request mỗi giờ"] --> F1["Standing Watch + token bucket"]
  P2["Bot vét bàn lúc mở bán"] --> F2["Fair Drop: xổ số có kiểm chứng"]
  P3["Agent đặt vượt ý người dùng"] --> F3["Standing mandate + step-up"]
  P4["Nhà hàng mất quyền kiểm soát"] --> F4["Luật Cedar + trần agent share"]
  P5["Alexa+ đúng khoảng 50% tác vụ"] --> F5["pass^k, C_out, ablation A0 vs A1"]
  P6["Quán nhỏ không có kênh cho agent"] --> F6["MCP storefront + onboarding"]
```

---

## 3. Tổng quan giải pháp

### 3.1 Bốn trụ cột

| Trụ cột | Người dùng thấy gì | Bên dưới là gì |
|---|---|---|
| **Standing Mandate + step-up** | Duyệt một lần trên điện thoại: "Luna, tối đa 4 người, 17–22h, không phí hủy". Booking nằm trong phạm vi → Alexa xác nhận ngay; vượt phạm vi → gửi link duyệt | Bản ghi mandate trong DynamoDB, thu hồi được; luật S3 quyết định xác nhận ngay hay step-up (-32042) |
| **Trust Pipeline 2 PEP** | Agent hợp lệ đặt trơn tru; bot bị chặn kèm lý do | PEP-1 ở Gateway (JWT, Cedar G1–G4, Guardrails) + PEP-2 trong server (cedarpy P0 + S1–S4 với bộ đếm trực tiếp) |
| **Fair Drop + Standing Watch** | "Đã ghi danh bạn vào lượt bốc thăm 10 giờ sáng" / "Có bàn 7:30 vừa trống" | Commit–reveal; MCP Task; sweeper + Streams + watch matcher |
| **Proven Reliability** | Biểu đồ pass^k A0 vs A1, bảng red-team trong video | Task generator + 2 simulator có tool + grader theo trạng thái DB |

### 3.2 Nguyên tắc thiết kế
1. **LLM không quyết định tiền và chỗ.** Phí, cọc và việc chọn slot do code tính; LLM chỉ chọn tool và diễn đạt [P1].
2. **Mọi hành động ghi phải gắn với một người thật đã xác minh.** Server tự xác minh token của người dùng, không tin vào Gateway [P30].
3. **Luật viết một ngôn ngữ (Cedar), thực thi hai chỗ.** Luật không trạng thái ở Gateway, luật có trạng thái trong server. Nếu Gateway gặp sự cố, chuyển luật G sang cedarpy chỉ là copy-paste [Suy luận].
4. **Cedar quyết định, DynamoDB bảo đảm.** Cedar đọc bộ đếm tại một thời điểm; điều kiện trong `TransactWriteItems` kiểm lại lần nữa khi ghi đồng thời [Suy luận].
5. **Không dựa vào TTL cho nghiệp vụ.** Sweeper + kiểm hạn khi đọc [P33].
6. **Không polling; công bằng phải kiểm chứng được; đo bằng số và ghi rõ cách đo.**

### 3.3 AI làm gì – code làm gì

| Việc | Ai làm |
|---|---|
| Hiểu yêu cầu, hỏi lại, gợi ý giờ khác | LLM (agent phía khách) |
| Chọn slot, giữ chỗ, tính cọc/phí, xổ số, quyết định luật | Code xác định + Cedar |
| Trích tham số luật từ câu nói của chủ quán | LLM → **chỉ điền vào template Cedar**, không viết Cedar tự do → người duyệt |
| Kiểm câu tóm tắt luật/phí | Automated Reasoning (offline) |
| Chấm chất lượng hội thoại | AgentCore Evaluations |

---

## 4. Danh tính & consent (mới trong v2)

### 4.1 Chuỗi danh tính

| Bước | Thiết kế | Kiểm chứng |
|---|---|---|
| **Liên kết tài khoản** | Simulator làm OAuth Authorization Code + **PKCE** với Cognito managed login – giống account linking của Alexa thật [Suy luận] | [AFD] |
| **Claim của agent** | Lambda pre-token thêm `agent_tier`, `agent_id`. **V2** chỉ tùy chỉnh access token khi *người dùng* đăng nhập; **token M2M (client-credentials) cần V3**. Cả hai đều cần gói **Essentials** trở lên | ✅ [P34] – bản AFD chỉ dùng V2 |
| **Cửa Gateway** | Authorizer `CUSTOM_JWT` với JWKS của Cognito + `allowedClients` | [AFD] |
| **Chuyển danh tính** | **REQUEST interceptor** (Lambda) chép token người dùng sang header `x-ft-user-token`. Vì Gateway gọi server bằng OAuth outbound của chính nó (AgentCore Identity) [S45], server sẽ không thấy token người dùng nếu thiếu bước này | ✅ Interceptor chạy trước khi request tới target [P28]; mặc định không nhận request header, trừ khi bật `passRequestHeaders` [P25]; chỉ header trong allowlist mới được chuyển tiếp [P27] |
| **Chống giả mạo header** | Interceptor **xóa mọi `x-ft-user-token` do client tự gửi** rồi mới ghi từ `Authorization` đã xác thực | [Suy luận] – test ở RT4 |
| **Xác minh lại ở server** | Server kiểm chữ ký, `aud`, `exp` bằng `joserfc` với JWKS của Cognito → có `sub`, `agent_tier` đáng tin | `joserfc` BSD-3 (PyPI) |
| **Gắn danh tính cho elicitation** | Mọi elicitation/step-up gắn với `sub` đã xác minh – spec 2025-11-25 **bắt buộc** server gắn yêu cầu elicitation với client và danh tính người dùng | ✅ [P30] |

### 4.2 Standing mandate & step-up

- **Standing mandate:** người dùng tạo trên trang consent (FastAPI trên Lambda, đăng nhập OIDC qua Cognito) và thu hồi được bất cứ lúc nào. Server đọc mandate **mỗi lần gọi**, nên thu hồi có hiệu lực ngay.
- **Step-up:** booking vượt phạm vi mandate → luật S3 trả `on_deny = step_up` → server trả lỗi JSON-RPC **-32042 (URLElicitationRequiredError)** kèm URL trang duyệt [P30]. Người dùng duyệt **trên điện thoại**; dữ liệu nhạy cảm không đi qua client hay model. Duyệt xong, agent gọi lại với cùng `idempotency_key`.
- **Lưu ý phiên bản:** -32042 chỉ có trong spec 2025-11-25; spec 2026-07-28 đã bỏ và giữ mã này ở trạng thái reserved [P31] → thêm một lý do để **bám 2025-11-25**.

```mermaid
sequenceDiagram
  autonumber
  actor U as Diner
  participant A as Alexa+ sim
  participant C as Cognito (Essentials)
  participant T as Lambda pre-token
  participant W as Consent web
  participant D as DynamoDB
  U->>A: Liên kết tài khoản FairTable
  A->>C: Authorization Code + PKCE (managed login)
  C->>T: trigger V2 (người dùng)
  T-->>C: thêm agent_tier = verified, agent_id
  C-->>A: access token + refresh token
  U->>W: Mở trang consent trên điện thoại (OIDC)
  U->>W: Luna, tối đa 4 người, 17-22h, phí hủy 0 USD, cho phép tự xác nhận
  W->>D: lưu MANDATE version 1 + audit
  Note over U,D: Về sau: trong phạm vi thì xác nhận ngay, vượt phạm vi thì step-up -32042
```

Bản ghi standing mandate (DynamoDB):
```json
{
  "PK": "USER#cog_8f2c", "SK": "MANDATE#luna-trattoria",
  "status": "active", "version": 1,
  "scope": {"party_size_max": 4, "days_ahead_max": 30, "time_window": "17:00-22:00",
            "max_deposit_usd": 50, "max_cancel_fee_usd": 0, "allow_auto_confirm": true,
            "actions": ["hold", "confirm", "watch", "drop_entry"]},
  "agent_ids": ["alexa-plus-sim"],
  "approved_at": "2026-10-05T14:02:11Z", "expires_at": "2026-12-31T23:59:59Z"
}
```
**Liên hệ chuẩn:** tinh thần giống token ủy quyền gắn với *tác vụ* thay vì *người dùng* trong các IETF draft 2026 [P11][P12] và mandate của AP2 [S26]. FairTable là bản rút gọn, lưu phía server. Xuất mandate thành token ký KMS cho agent bên thứ ba là hạng mục **Could**.

---

## 5. Thiết kế MCP

### 5.1 Bề mặt MCP

| Thành phần | Thiết kế |
|---|---|
| **Server** `fairtable` | Spec **2025-11-25**, Streamable HTTP, **stateful** [S41]. Chạy trên AgentCore Runtime, đứng sau Gateway dạng MCP target (OAuth) [S42][S45] |
| **Phiên bản đã ghim** | **FastMCP 3.4.7** (bản 3.x cuối, 10/08/2026; 4.0 mới ra 31/08/2026 nên chưa dùng) · **mcp 1.30.0** (bản mới nhất nhánh 1.x; `pip install mcp` giờ ra 2.x [S60]) · **Strands 1.57.1** · **cedarpy 4.12.1** · **joserfc** · **mangum** – kiểm PyPI ngày 28/09/2026 [P38]. FastMCP dùng giấy phép **Apache-2.0** (đính chính v1, trước đó ghi MIT) |
| **Tools** | 8 tool cho agent (mục 5.2); chủ quán dùng web, MCP riêng cho chủ quán là Could |
| **Resources** | `fairtable://restaurants/{id}/policies` (văn bản luật EN, cũng là input cho Automated Reasoning) · `fairtable://drops/{drop_id}/audit` |
| **Tasks** | `waitlist_watch` hỗ trợ task (`taskSupport: optional`) [P17]; FastMCP có sẵn `task=True` [P18] ❓ cần thử trên Runtime |
| **MCP Apps** | `ui://fairtable/slot-picker`, `ui://fairtable/booking-card`. Simulator dùng **AppBridge** – SDK chính thức cho phía host (`@modelcontextprotocol/ext-apps/app-bridge`) để render trong iframe sandbox [P37] |

### 5.2 Danh mục tool (8)

| Tool | Loại | Input chính | Output chính | Luật liên quan | Lỗi có cấu trúc |
|---|---|---|---|---|---|
| `restaurant_search` | đọc | `query`, `date?`, `party_size?`, `response_format` | quán + tóm tắt luật + giờ trống gần nhất | G1 | `INVALID_INPUT` |
| `availability_check` | đọc | `restaurant_id`, `date`, `time_window`, `party_size` | `slots[]` (`slot_token`, `terms`, `hot`, `drop_id?`), `spoken_summary`, `next_step` | G1, token bucket | `RATE_LIMITED` |
| `mandate_status` | đọc | `restaurant_id` | phạm vi standing mandate hiện tại + những gì cần step-up | G1 | `NOT_FOUND` + `consent_url` |
| `reservation_hold` | ghi | `slot_token`, `idempotency_key` | `hold_id`, `expires_at`, `terms`, `within_mandate` | G2–G4, S1, S2, S4 | `SLOT_TAKEN`, `POLICY_DENIED`, `DROP_CONTROLLED`, `IDEMPOTENCY_CONFLICT` |
| `reservation_confirm` | ghi | `hold_id`, `idempotency_key` | `reservation_id`, `code`, `terms_snapshot` + booking card | G2–G4, **S3** | `HOLD_EXPIRED`; **-32042** khi cần step-up |
| `reservation_manage` | ghi | `action` (view/modify/cancel), `reservation_id`, `idempotency_key` | kết quả; phí tính **trước** khi hủy | G2–G4, S3 | `FEE_APPLIES` → -32042 |
| `waitlist_watch` | ghi | `restaurant_id`, `date`, `window`, `party_size` | `watch_id` / task; slot "hot" tự thành phiếu Fair Drop | S2, 1 watch/người/ngày | `ALREADY_ENTERED`, `DROP_CLOSED` |
| `waitlist_status` | đọc | `watch_id`, `action` (status/cancel) | trạng thái (cho client không hỗ trợ Tasks) | G1 | `NOT_FOUND` |

`mandate_status` là tool **mới** [Suy luận]: giúp agent biết trước booking nào xác nhận được ngay và booking nào phải step-up, để nói trước với người dùng thay vì bất ngờ.

### 5.3 Hợp đồng & lỗi

**Idempotency** [AFD]:
- Khóa theo (`sub`, `idempotency_key`).
- Cùng tham số → trả **kết quả đã lưu**.
- Khác tham số → `IDEMPOTENCY_CONFLICT`.
- Chỉ lưu khi trạng thái thật sự thay đổi, nên gọi lại sau step-up với cùng khóa vẫn hợp lệ [Suy luận].

**Hai loại lỗi:**
- **Lỗi thực thi tool** (`isError: true`) có trường cấu trúc để model tự sửa. Spec 2025-11-25 làm rõ rằng lỗi kiểm tra input nên trả dạng này thay vì lỗi protocol [P32].
- **Lỗi protocol -32042** chỉ dùng cho step-up [P30].

```json
{
  "error": "RATE_LIMITED",
  "retry_after_s": 60,
  "next_step": {"tool": "waitlist_watch", "why": "Register once; you will be notified when a table opens."},
  "message": "Too many availability checks for this venue."
}
```
```json
{
  "error": "POLICY_DENIED",
  "rule_id": "S2_agent_share_of_covers",
  "hint": "Agent bookings for Saturday are full. Suggest calling the restaurant or joining the waitlist.",
  "next_step": {"tool": "waitlist_watch"}
}
```

**Quy tắc viết tool** [P21]:
- Ít tool, mỗi tool khớp một bước của luồng công việc.
- Tên có namespace.
- Trả trường dễ đọc cho người, không trả ID thô.
- Có `response_format` concise/detailed.
- Lỗi phải chỉ ra cách sửa; có `next_step`.
- Mọi output có `spoken_summary` ngắn cho giọng nói.

### 5.4 Mô hình dữ liệu v2 (DynamoDB single-table)

| Thực thể | PK | SK | Ghi chú |
|---|---|---|---|
| Nhà hàng + luật | `REST#{rid}` | `PROFILE` / `POLICY#v{n}` | Luật có version; `agent_cover_cap` theo ngày |
| Slot | `REST#{rid}#D#{date}` | `SLOT#{hhmm}#{table_group}` | `status`, `ver`, `hot`, `drop_id` |
| Hold | `HOLD#{hold_id}` | `META` | `expires_at`; **GSI1** theo bucket giờ hết hạn để sweeper quét [Suy luận] |
| Đặt chỗ | `RES#{res_id}` | `META` | **GSI2** theo `USER#{sub}` |
| Standing mandate | `USER#{sub}` | `MANDATE#{rid}` | mục 4.2 |
| Bộ đếm S1 | `CNT#USER#{sub}#REST#{rid}` | `ACTIVE_HOLDS` | điều kiện `< 2` trong transaction |
| Bộ đếm S2 | `CNT#REST#{rid}#D#{date}` | `AGENT_COVERS` | điều kiện `+ party ≤ cap` trong transaction |
| Watch / Drop / phiếu | `WATCH#…` · `DROP#{id}` | `…` · `ENTRY#{hash(sub)}` | `attribute_not_exists` → 1 phiếu/người |
| Idempotency | `IDEM#{sub}#{key}` | `META` | `params_hash`, kết quả |
| Audit | `AUDIT#{rid}#{date}` | `{ts}#{req_id}` | ai · tool · quyết định · `rule_id` |

**Một lần giữ chỗ = một `TransactWriteItems`** gồm 5 thao tác:
1. Cập nhật slot với điều kiện `status = open AND ver = v`.
2. Tăng bộ đếm S1 với điều kiện `< 2`.
3. Tăng bộ đếm S2 với điều kiện `+ party ≤ cap`.
4. Ghi HOLD + IDEM.
5. Ghi AUDIT.

Một điều kiện hỏng → cả giao dịch bị hủy → trả `SLOT_TAKEN` hoặc `POLICY_DENIED` [Suy luận].

---

## 6. Trust Pipeline – 2 điểm thực thi luật (PEP)

```mermaid
flowchart TD
  R["tools/call tới Gateway, Bearer của người dùng"] --> J1{"JWT hợp lệ? Cognito JWKS, allowedClients"}
  J1 -- Không --> X1["401"]
  J1 -- Có --> IC["REQUEST interceptor: xóa header giả, chép user token sang x-ft-user-token"]
  IC --> P1{"Cedar PEP-1: G1-G4 cho phép?"}
  P1 -- Không --> X2["Tool bị ẩn hoặc từ chối"]
  P1 -- Có --> RV["Runtime: xác minh lại user token bằng joserfc"]
  RV --> RO{"Tool đọc?"}
  RO -- Có --> TB{"Token bucket OK?"}
  TB -- Không --> X3["RATE_LIMITED + retry_after + next_step waitlist_watch"]
  TB -- Có --> OR["Kết quả đọc + next_step"]
  RO -- Không --> ID{"Idempotency key đã thấy?"}
  ID -- Cùng tham số --> OLD["Trả kết quả đã lưu"]
  ID -- Khác tham số --> X4["IDEMPOTENCY_CONFLICT"]
  ID -- Mới --> CX["Dựng Cedar context từ DynamoDB: bộ đếm + standing mandate"]
  CX --> P2{"Cedar PEP-2: P0 + S1-S4"}
  P2 -- deny --> X5["POLICY_DENIED + rule_id + hint"]
  P2 -- step-up --> X6["-32042 + URL consent"]
  P2 -- allow --> TX["TransactWriteItems: slot, bộ đếm, hold, idem, audit"]
  TX --> CD{"Điều kiện ghi thỏa?"}
  CD -- Không --> X7["SLOT_TAKEN + alternatives"]
  CD -- Có --> OK["audit + kết quả + booking card"]
```

### 6.1 PEP-1 – AgentCore Policy ở Gateway (không trạng thái)

Luật viết bằng tiếng Anh thường, AgentCore dịch sang Cedar [S37]; Guardrails chạy ngay tại Gateway [S38].
- **G1:** tool đọc – mọi caller có JWT hợp lệ.
- **G2:** tool ghi – principal phải có `username` (tức người dùng thật) và scope `fairtable/book`.
- **G3:** `party_size > 10` → forbid; nhóm lớn gọi thẳng cho quán.
- **G4:** forbid, *trừ khi* `principal has agent_tier && principal.agent_tier == "verified"`.

❓ Tên entity và thuộc tính cụ thể phụ thuộc schema mà Gateway sinh ra, cần viết thử ngay tuần 2.

**Vì sao G4 bắt buộc có `has`-guard (đã thử bằng cedarpy 4.12.1):** giả lập token M2M của bot có scope `fairtable/book` nhưng **thiếu** claim `agent_tier` (đúng kịch bản khi chỉ bật trigger V2 [P34]):

| Cách viết G4 | Kết quả thật khi chạy |
|---|---|
| `forbid … when { principal.agent_tier != "verified" }` | **Allow** – policy lỗi vì thiếu thuộc tính, bị bỏ qua, và permit G2 thắng |
| `forbid … unless { principal has agent_tier && principal.agent_tier == "verified" }` | **Deny** – đúng ý đồ |

→ Cần **cả hai**: trigger **V3** để token M2M cũng mang claim, **và** `has`-guard phòng khi cấu hình sai.

### 6.2 PEP-2 – Trust Kernel trong server (cedarpy, có trạng thái)

Đoạn Cedar dưới đây **đã chạy thử** với `cedarpy` 4.12.1, cho kết quả đúng ở cả 7 tình huống: happy path, S1, S2, S3 thiếu mandate, S3 có mandate, S4, agent chưa verified.

```cedar
@id("P0_base")
permit (
  principal is Diner,
  action in [Action::"reservation_hold", Action::"reservation_confirm",
             Action::"reservation_manage", Action::"waitlist_watch"],
  resource is Venue
)
when { context.agent_tier == "verified" };

@id("S1_max_active_holds") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.active_holds_user_venue >= 2 };

@id("S2_agent_share_of_covers") @on_deny("deny")
forbid (principal, action in [Action::"reservation_hold", Action::"waitlist_watch"], resource)
when { context.agent_covers_booked + context.party_size > resource.agent_cover_cap };

@id("S3_confirm_needs_mandate") @on_deny("step_up")
forbid (principal, action == Action::"reservation_confirm", resource)
unless { context.mandate_covers_booking };

@id("S4_drop_slots_via_waitlist") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.slot_is_drop_controlled };
```

**Cách server đọc kết quả** (đã kiểm): cedarpy trả lý do dạng `policy0…policy4`, nhưng khi xuất policy sang JSON thì annotation `id` và `on_deny` vẫn giữ nguyên. Server dựng bảng `policyN → (rule_id, on_deny)` một lần lúc khởi động, rồi áp thứ tự ưu tiên [Suy luận]:
1. Có forbid `deny` → `POLICY_DENIED` kèm `rule_id`.
2. Chỉ có forbid `step_up` → -32042.
3. Allow → ghi.
4. Không có permit nào khớp (ví dụ agent chưa verified) → `POLICY_DENIED` với lý do "no permit".

`agent_cover_cap` được tính từ phần trăm chủ quán đặt × tổng số chỗ trong ngày [Suy luận].

### 6.3 Luật nằm ở đâu

| Lớp | Nơi thực thi | Lý do |
|---|---|---|
| JWT, allowedClients | Gateway `CUSTOM_JWT` | Chặn sớm, rẻ |
| G1–G4 (không trạng thái) | AgentCore Policy + Guardrails [S37][S38] | Chặn **trước** khi tool chạy, độc lập với LLM |
| Xác minh lại token | Server (`joserfc`) | Không tin mù vào header |
| Token bucket, idempotency | Server + DynamoDB | Cần trạng thái |
| P0, S1–S4 | Server (`cedarpy`) | Cần bộ đếm trực tiếp + mandate |
| Ràng buộc cuối cùng | Điều kiện trong `TransactWriteItems` | An toàn khi có ghi đồng thời |

---

## 7. Các pipeline chính

### 7.1 Đặt bàn – trong phạm vi mandate thì xác nhận ngay, vượt thì step-up

```mermaid
sequenceDiagram
  autonumber
  actor U as Diner
  participant A as Alexa+ sim
  participant G as Gateway PEP-1
  participant S as FairTable MCP PEP-2
  participant D as DynamoDB
  participant P as Điện thoại
  U->>A: Bàn 6 người ở Luna, thứ Bảy 7 giờ
  A->>G: availability_check + Bearer
  G->>S: G1 cho phép, interceptor gắn x-ft-user-token
  S->>S: xác minh lại token bằng joserfc
  S->>D: đọc slot
  S-->>A: 19:00 + điều khoản + next_step
  A->>U: Có 7 giờ, bạn lấy không?
  U->>A: Lấy
  A->>G: reservation_hold(slot_token, idempotency_key)
  G->>S: G2-G4 cho phép
  S->>D: đọc bộ đếm + standing mandate
  S->>S: cedarpy S1, S2, S4 cho phép
  S->>D: TransactWriteItems slot, bộ đếm, hold, idem, audit
  S-->>A: hold_id, within_mandate = false vì mandate tối đa 4 người
  A->>G: reservation_confirm(hold_id, idempotency_key)
  S->>S: cedarpy S3 yêu cầu step-up
  S-->>A: lỗi -32042 kèm URL duyệt
  A->>U: Nhóm 6 người vượt phạm vi bạn cho phép, mở link trên điện thoại để duyệt
  U->>P: Duyệt booking này, phí hủy 10 USD mỗi người sau mốc 24h
  P->>D: lưu phê duyệt một lần cho hold này
  A->>G: reservation_confirm thử lại với cùng idempotency_key
  S->>S: cedarpy S3 cho phép
  S->>D: HOLD thành CONFIRMED + audit
  S-->>A: mã LUN-4821 + booking card
  A->>U: Đã đặt 7 giờ thứ Bảy cho 6 người, mã LUN-4821
```

Đây chính là chỗ agent trong bài CNN đã bỏ qua [S20]: điều khoản vượt phạm vi nên hệ thống **buộc** phải hỏi người dùng, và việc hỏi diễn ra ngoài hội thoại, trên điện thoại.

### 7.2 Standing Watch – thay polling

```mermaid
sequenceDiagram
  autonumber
  participant A as Alexa+ sim
  participant S as FairTable MCP
  participant D as DynamoDB
  participant E as Scheduler + sweeper
  participant M as Lambda watch-matcher
  A->>S: waitlist_watch(Luna, T7 19-21h, 4 người) dạng task
  S->>D: lưu WATCH, 1 watch mỗi người mỗi ngày
  S-->>A: task_id, status working
  Note over D,E: Một hold khác hết hạn mà không được xác nhận
  E->>D: sweeper trả slot 19:30, chạy mỗi 1 phút
  D->>M: Streams báo slot mở
  M->>D: chọn watcher hợp lệ đầu tiên, tạo HOLD 10 phút
  M->>S: cập nhật task thành input_required hoặc completed
  A->>S: tasks/get(task_id)
  S-->>A: Có bàn 19:30
  A->>S: reservation_confirm(hold_id, idempotency_key)
  S-->>A: đã xác nhận vì mandate phủ booking
```

Tasks vẫn là tính năng thử nghiệm trong 2025-11-25 [P17]. Client nào không hỗ trợ thì dùng `waitlist_status`; server trả `next_step` và `retry_after` để agent không gọi dồn dập.

### 7.3 Fair Drop – xổ số commit–reveal

```mermaid
sequenceDiagram
  autonumber
  participant O as Luật chủ quán
  participant E as EventBridge Scheduler
  participant S as FairTable MCP
  participant L as Lambda allocator
  participant K as KMS
  participant A as Nhiều agent
  O->>S: Bàn tối T6-T7 mở trước 14 ngày lúc 10:00, trần agent share 60 phần trăm
  S->>K: GenerateRandom tạo seed
  S-->>A: công bố commitment bằng SHA-256(seed) và luật xổ số
  Note over A,S: T trừ 10 phút mở nhận phiếu
  A->>S: waitlist_watch(drop_id), 1 phiếu mỗi người đã xác minh
  S-->>A: entry_id, task working
  E->>L: đến giờ T, đóng cửa và phân bổ
  L->>L: thứ tự bằng HMAC(seed, entry_id), tôn trọng mandate và trần S2
  L->>S: tạo HOLD cho người thắng bằng TransactWriteItems
  S-->>A: task completed nếu mandate phủ, nếu không thì step-up
  L->>S: công bố audit gồm seed, phiếu đã băm, thứ tự
```

**Cơ sở và rủi ro:**
- Xổ số cho mọi người cơ hội ngang nhau, còn "ai đến trước" buộc người mua cạnh tranh bằng thời gian xếp hàng [P9].
- Người mua có thể nghi ngờ việc bốc thăm bị gian lận, và xổ số tạo động cơ lách luật [P8] → commit–reveal + audit công khai + 1 phiếu/người đã xác minh.
- Trần **S2** giữ lại phần chỗ cho khách gọi điện và khách vãng lai.

### 7.4 Chủ quán đổi luật – LLM chỉ điền template

```mermaid
sequenceDiagram
  autonumber
  actor O as Chủ quán
  participant W as Owner web
  participant LLM as Bedrock trích xuất
  participant V as cedarpy validate
  participant AR as Automated Reasoning
  participant D as DynamoDB
  O->>W: Nhóm từ 6 người cọc 20 USD mỗi người, agent chỉ được 60 phần trăm số chỗ
  W->>LLM: trích xuất tham số mẫu luật + câu tóm tắt tiếng Anh
  LLM-->>W: deposit_min_party=6, deposit_per_person=20, agent_cover_share=0.6
  W->>V: điền tham số vào template Cedar và validate
  W->>AR: kiểm câu tóm tắt so với văn bản luật của quán
  AR-->>W: VALID hoặc INVALID kèm giải thích
  W->>O: hiển thị diff + kết quả kiểm chứng
  O->>W: Duyệt
  W->>D: lưu luật version mới + audit
```

Automated Reasoning chỉ hỗ trợ tiếng Anh (US) và không hỗ trợ streaming [S33], nên chỉ dùng ở luồng này, không dùng khi nói chuyện với khách.

### 7.5 Onboarding từ website (stretch) – dual-LLM

```mermaid
flowchart LR
  URL["Link website của quán"] --> NA["AgentCore Browser + Nova Act, cách ly"]
  NA --> RAW["Nội dung web, dữ liệu không tin cậy"]
  RAW --> QX["LLM cách ly: chỉ trích xuất theo schema, không có tool"]
  QX --> J["JSON: giờ mở cửa, sức chứa, luật đặt bàn"]
  J --> V["Validator: schema + giới hạn giá trị"]
  V --> OWN{"Chủ quán duyệt?"}
  OWN -- Duyệt --> CFG["Cấu hình storefront"]
  OWN -- Sửa --> J
```

### 7.6 Vòng đời slot

```mermaid
stateDiagram-v2
  [*] --> Open
  Open --> Held: reservation_hold hoặc thắng xổ số
  Held --> Open: sweeper trả hold hết hạn hoặc hủy hold
  Held --> Confirmed: reservation_confirm khi mandate phủ hoặc đã step-up
  Confirmed --> Cancelled: reservation_manage cancel
  Confirmed --> Seated: check-in tại quán
  Confirmed --> NoShow: quá giờ 15 phút
  Cancelled --> Open: trả slot, Streams kích hoạt watch-matcher
  Seated --> [*]
  NoShow --> [*]
```

---

## 8. Kỹ thuật agentic áp dụng (v2)

| # | Kỹ thuật | Nguồn | Áp dụng | Mức |
|---|---|---|---|---|
| 1 | Action-Selector / Plan-then-Execute / Dual-LLM | [P1][P2]; phần dư chưa chặn được 🟡 [P22] | Tool xác định; chủ quán đổi luật theo kiểu điền template; onboarding cách ly | Must |
| 2 | **Hai PEP cùng ngôn ngữ Cedar** | AgentCore Policy [S37]; Policy kết hợp interceptor [P28]; cedarpy [P39] | G1–G4 ở Gateway, P0 + S1–S4 trong server | Must |
| 3 | **Chuyển danh tính qua interceptor + xác minh lại** | [P25][P26][P27][P28][P29]; spec bắt buộc gắn elicitation với danh tính [P30] | Header `x-ft-user-token`, `joserfc` | Must |
| 4 | **Step-up bằng URL elicitation (-32042)** | [P30]; đã bị bỏ ở 2026-07-28 [P31] | Vượt phạm vi mandate → duyệt trên điện thoại | Must |
| 5 | Delegation có phạm vi | IETF drafts [P11][P12]; AP2 [S26] | Standing mandate lưu phía server | Must |
| 6 | MCP Tasks | [P17][P18][P19] | Standing Watch, phiếu Fair Drop | Must |
| 7 | Xổ số commit–reveal | [P8][P9] | Fair Drop | Must |
| 8 | **pass^k + C_out** | pass^k [S30]; C_out = trung bình (2p̂−1)² theo task [P35] | Báo cáo độ tin cậy | Must |
| 9 | **Ablation có đối chứng** | [AFD] | A0 cửa hàng mở · A1 FairTable · A2 không step-up | Must |
| 10 | Task generator ghép thành phần + simulator có tool | τ²-bench [P4] | 40 task, simulator có `say / approve_consent / decline` | Must |
| 11 | Nhiều simulator + persona không hợp tác | [P5][P6][P7] | Sim A + Sim B | Should |
| 12 | Automated Reasoning | [S32][S33] | Kiểm câu tóm tắt luật (offline) | Should |
| 13 | MCP Apps qua AppBridge | [S56][P37] | Slot picker, booking card | Should |
| 14 | ACE | [P3] | Cải thiện mô tả tool từ lỗi eval, có người duyệt | Could |
| 15 | Nova 2 Sonic, Web Bot Auth, Memory | [S54][S29][S48] | Voice, danh tính agent bằng chữ ký, sở thích khách | Could |

---

## 9. Đánh giá & red-team (v2)

### 9.1 Bộ task
- **40 task YAML:** HAPPY 12 · NEG 8 · ROB 8 · ADV 12 [AFD]. Mỗi task ghép từ quán × mục tiêu × nhiễu × tấn công.
- Generator ghép thành phần theo kiểu τ²-bench [P4].
- **Mỗi lần chạy dùng một namespace DynamoDB mới** [AFD].
- Mỗi task có trạng thái đích và các bất biến I1–I5 (giữ từ v1):
  - I1: không có đặt chỗ nào ngoài phạm vi mandate.
  - I2: không trùng chỗ.
  - I3: phí luôn được thông báo và chấp nhận trước khi ghi.
  - I4: 1 phiếu/người/drop.
  - I5: không có thao tác ghi nào thiếu danh tính đã xác minh.

### 9.2 User simulator
- **Sim A** (model 1, hợp tác) và **Sim B** (model 2, persona "vội" và "bỏ đi"). Tỷ lệ thành công có thể lệch tới 9 điểm % tùy simulator, nên báo cáo **tách riêng** từng simulator [P5].
- Simulator hành động qua **tool**: `say`, `approve_consent`, `decline` [AFD]. Nhờ đó bước duyệt trên điện thoại được mô phỏng đúng, và simulator bị ràng buộc bởi môi trường như τ²-bench [P4].

### 9.3 Ablation [AFD]

| Cấu hình | Mô tả | Chứng minh điều gì |
|---|---|---|
| **A0** | Cửa hàng mở: allow-all, không Trust Kernel (kiểu OpenBook/G-Guest) | Mốc so sánh |
| **A1** | FairTable đầy đủ | Lớp tin cậy giảm vi phạm mà **không** làm giảm pass^k của task hợp lệ |
| **A2** | FairTable nhưng luôn xác nhận trong hội thoại (không step-up) | Giá trị riêng của step-up |

### 9.4 Grader & chỉ số
- **Grader:** state grader (trạng thái DB) · safety grader (không consent, vượt mandate, >2 hold, ghi khi chưa verified, sai phí) · AgentCore Evaluations (LLM-as-judge) · disclosure checker (so khớp chính xác; Automated Reasoning offline là stretch).
- **Chỉ số:**
  - **pass@1**
  - **pass^k** = E[C(c,k)/C(n,k)] [S30]
  - **C_out** = (1/T)·Σ(2p̂ₜ−1)² [P35]. Paper gốc ghi nhận các model có outcome consistency chỉ từ 30% đến 75% [P36].
  - Tỷ lệ vi phạm · block rate · **false-block rate** (chặn nhầm task hợp lệ) · p50/p95 · cost/booking.

```mermaid
flowchart LR
  SP["Task specs YAML: HAPPY 12, NEG 8, ROB 8, ADV 12"] --> GN["Generator ghép thành phần"]
  GN --> SD["Seed DynamoDB, namespace mới"]
  SD --> UA["User sim A: say, approve_consent, decline"]
  SD --> UB["User sim B: persona vội hoặc bỏ đi"]
  UA <--> AG["Alexa+ sim agent, cùng code demo"]
  UB <--> AG
  AG <--> FD["FairTable cấu hình A0, A1, A2"]
  RT["Red-team RT1-RT12"] --> FD
  FD --> ST["DynamoDB trạng thái cuối"]
  AG --> TR["OTel traces"]
  ST --> G1["State grader"]
  ST --> G2["Safety grader"]
  TR --> G3["AgentCore Evaluations"]
  TR --> G4["Disclosure checker"]
  G1 --> MT["pass@1, pass^k, C_out, vi phạm, false-block, p95, cost"]
  G2 --> MT
  G3 --> MT
  G4 --> MT
  MT --> RP["Báo cáo A0 vs A1, tách theo simulator"]
  RP --> GT{"Regression gate"}
  GT -- Đạt --> SH["Tag release, cập nhật demo"]
  GT -- Không đạt --> FX["Quay lại code"]
  RP -.-> ACE["Vòng ACE: delta mô tả tool, người duyệt, held-out"]
```

### 9.5 Red-team (RT1–RT12)

| ID | Tấn công | Kết quả mong đợi | Lớp chặn |
|---|---|---|---|
| RT1 | Bot M2M gọi tool ghi | Bị ẩn hoặc từ chối (không có `username`) | PEP-1 G2 |
| RT2 | `availability_check` 300 lần/giờ | `RATE_LIMITED` + `next_step` | PEP-2 token bucket |
| RT3 | Token M2M thiếu `agent_tier` | Deny (nhờ `has`-guard) | PEP-1 G4 |
| RT4 | Client tự gửi `x-ft-user-token` giả | Interceptor xóa header; server xác minh chữ ký thất bại | Interceptor + server |
| RT5 | Nhóm 6 người trong khi mandate tối đa 4 | Step-up -32042, **không** đặt lặng lẽ | PEP-2 S3 |
| RT6 | Giữ chỗ lần thứ 3 ở cùng một quán | Deny | PEP-2 S1 + điều kiện DB |
| RT7 | Trần agent share đã đầy | Deny + gợi ý gọi quán | PEP-2 S2 |
| RT8 | Giữ thẳng slot thuộc drop | Deny + `next_step: waitlist_watch` | PEP-2 S4 |
| RT9 | 20 lệnh giữ chỗ đồng thời một slot | Đúng 1 thành công | `TransactWriteItems` |
| RT10 | Dùng lại idempotency key với tham số khác | `IDEMPOTENCY_CONFLICT` | Server |
| RT11 | Prompt injection trong `special_requests` | Không có tác dụng (chỉ là dữ liệu) + Guardrails | Thiết kế + PEP-1 |
| RT12 | Một người nộp nhiều phiếu drop | Phiếu thứ hai bị từ chối | Điều kiện DB |

**Mẫu báo cáo** (không công bố số chưa đo):

| Chỉ số | A0 | A1 | A2 | Ghi chú |
|---|---|---|---|---|
| pass^1 / pass^4 (HAPPY + ROB) | … | … | … | Sim A và Sim B tách riêng |
| C_out | … | … | … | |
| Vi phạm (safety grader) | … | … | … | mục tiêu A1 = 0 |
| Red-team bị chặn | …/12 | …/12 | …/12 | |
| False-block rate | – | … | … | |
| Cost/booking | … | … | … | |

### 9.6 Nhịp chạy & ngân sách [AFD + Suy luận]

| Lượt | Cấu hình | Số hội thoại | Ước chi phí |
|---|---|---|---|
| Hằng ngày (local) | A1 · 10 task × k=2 · Sim A | 20 | ~1–2 USD |
| Hằng tuần × 2 (cloud) | A1 40×4 (Sim A) + A0 20×4 (NEG + ADV) + A2 20×4 (NEG) | 320 | ~16–32 USD/lần |
| Chốt | A0 + A1 · 12 task × k=8 · 2 simulator | 384 | ~19–38 USD |

**Tổng ước khoảng 70–130 USD**, dựa trên mốc khoảng 0,05 USD mỗi hội thoại của OpenBook [S13]. Con số này sát mức credit 150 USD [S1], nên **AWS Budgets cảnh báo ở $50/$100/$140** là bắt buộc. Regression gate: không merge nếu tệ hơn baseline.

---

## 10. Kiến trúc AWS & tech stack (v2)

Diagram: `fairtable-aws-architecture.drawio`. Tên icon được đối chiếu tự động với mã nguồn draw.io [P23]; EventBridge Scheduler dùng đúng shape cấp resource.

Kiến trúc chia thành 7 lane:
1. Identity & consent
2. Gateway – PEP-1
3. Runtime – PEP-2
4. Async: holds & công bằng
5. Intelligence & verification
6. Quality · observability · cost
7. Owner onboarding (stretch)

| Layer | Chọn | Vì sao | Xác minh |
|---|---|---|---|
| MCP server | FastMCP 3.4.7 + mcp 1.30.0 trên AgentCore Runtime, stateful | [S41]; ghim bản ổn định [P38] | ✅ |
| Trust Kernel | `cedarpy` 4.12.1 (Apache-2.0, có wheel ARM64) + `joserfc` | Luật có trạng thái bằng Cedar | ✅ đã chạy thử |
| Gateway | `CUSTOM_JWT` + REQUEST interceptor + Policy + Guardrails; outbound OAuth qua AgentCore Identity | [P25][P28][S37][S38][S45] | ✅ / ❓ schema Cedar |
| Danh tính | Cognito **Essentials** + pre-token **V2 (user) + V3 (M2M)** | [P34] | ✅ |
| Consent + owner web | API Gateway HTTP API + Lambda (FastAPI + **Mangum**, MIT) | Python, làm một mình | ✅ license |
| Dữ liệu | DynamoDB single-table + GSI1/GSI2 + Streams + `TransactWriteItems` | Mục 5.4 | [Suy luận] |
| Async | EventBridge Scheduler (mỗi 1 phút + giờ drop) → Lambda sweeper / allocator; Streams → watch matcher | Không dựa TTL [P33] | ✅ |
| Xổ số | KMS `GenerateRandom` tạo seed; HMAC-SHA256 dùng seed làm khóa (ai cũng tính lại được) | [Suy luận] | [Suy luận] |
| Agent client | Strands 1.57.1 (Apache-2.0) + TasksConfig; AppBridge cho MCP Apps | [S59][P19][P37] | ✅ |
| Model | Bedrock: Claude Haiku 4.5 cho agent và simulator; model lớn hơn cho judge | [S13] | 🟡 cần kiểm giá |
| Quan sát & chi phí | CloudWatch / AgentCore Observability → AgentCore Evaluations; **AWS Budgets** | [S67] | ✅ |
| UI host | Simulator chạy **local** trong MVP; CloudFront + S3 sau MVP (kiêm thư mục khóa Web Bot Auth) | Rẻ, ít thành phần | [Suy luận] |
| IaC | `agentcore` CLI (Runtime/Gateway) + AWS CDK Python | [S39][S74] | [Suy luận] |
| AI coding | Kiro – thể lệ ghi Kiro Crew đủ điều kiện AWS Builder [S1] | | ✅ |

**Region:** us-east-1 [S52][S37][S38][S33].

---

## 11. Phạm vi & kế hoạch 25 ngày (v2)

| Mức | Hạng mục |
|---|---|
| **Must** | 8 tool + DynamoDB; Trust Kernel cedarpy (P0, S1–S4) + idempotency + `TransactWriteItems`; hold sweeper; Cognito Essentials + pre-token V2/V3 + account linking PKCE; consent web + standing mandate + step-up -32042; Gateway `CUSTOM_JWT` + interceptor + Policy G1–G4; Standing Watch; Fair Drop; simulator dạng text; eval 40 task + A0/A1/A2 + RT1–RT12; Budgets |
| **Should** | Sim B; MCP Apps qua AppBridge; Automated Reasoning ở luồng chủ quán; owner web đầy đủ (agent share, audit) |
| **Could** | Nova 2 Sonic; Nova Act onboarding; Web Bot Auth; ACE; AgentCore Memory; xuất mandate thành token ký KMS |

```mermaid
gantt
  title Kế hoạch 25 ngày v2 (solo, Python)
  dateFormat YYYY-MM-DD
  axisFormat %d/%m
  section Nền tảng
  MCP server local FastMCP 3.4.7, DynamoDB, 8 tool :a1, 2026-09-29, 4d
  Trust Kernel cedarpy, idempotency, TransactWriteItems :a2, 2026-10-01, 3d
  Eval harness v0, 10 task, A0 vs A1 :a3, 2026-10-03, 3d
  section Danh tính và consent
  Cognito Essentials, pre-token V2 V3, PKCE :b1, 2026-10-05, 2d
  Consent web, standing mandate, step-up -32042 :b2, 2026-10-06, 3d
  Gateway CUSTOM_JWT, interceptor, Policy G1-G4 :b3, 2026-10-08, 3d
  Mốc fallback chuỗi danh tính :milestone, m1, 2026-10-11, 0d
  section Async và công bằng
  Hold sweeper, Budgets, observability :c1, 2026-10-09, 2d
  Standing Watch bằng Tasks và Streams :c2, 2026-10-11, 2d
  Fair Drop commit-reveal :c3, 2026-10-12, 3d
  section Trải nghiệm
  Alexa+ simulator web, AppBridge :d1, 2026-10-13, 4d
  Voice Nova 2 Sonic stretch :d2, 2026-10-16, 2d
  section Chất lượng
  Eval 40 task, 2 sim, A0 A1 A2, RT1-RT12 :e1, 2026-10-14, 5d
  Automated Reasoning luồng chủ quán :e2, 2026-10-17, 2d
  section Nộp bài
  Đóng băng tính năng :milestone, m2, 2026-10-20, 0d
  Video, feedback, friction log :f1, 2026-10-20, 2d
  Nộp bài, còn 1 ngày dự phòng :milestone, m3, 2026-10-22, 0d
```

**Các mốc chuyển fallback (v2):**
- **11/10 – chuỗi danh tính qua Gateway chưa chạy end-to-end:** cho simulator gọi **thẳng Runtime** với JWT inbound; chuyển G1–G4 sang cedarpy (cùng ngôn ngữ Cedar, gần như copy-paste). An toàn giữ nguyên; Gateway + Policy lùi sang giai đoạn 2 [Suy luận].
- **14/10 – Policy trên MCP target vướng schema:** giữ Gateway cho JWT + interceptor, luật G chạy ở PEP-2.
- **16/10 – client Tasks lỗi:** dùng `waitlist_status` + `next_step` + `retry_after`.
- **17/10 – voice chưa xong:** text + TTS.
- **Budgets chạm mốc $100:** chỉ chạy eval local với Sim A cho tới lượt chốt.

---

## 12. Kịch bản video (≤ 3 phút, tiếng Anh)

| Thời gian | Nội dung | Tiêu chí |
|---|---|---|
| 0:00–0:15 | Hook: agent gửi yêu cầu hàng trăm lần/giờ, tài khoản bị khóa (chỉ ghi tên nguồn, không dùng logo/footage bên thứ ba [S1]) | Quality |
| 0:15–0:55 | Đặt bàn bằng giọng nói: trong phạm vi mandate → xác nhận ngay; nhóm 6 người → **step-up trên điện thoại** | Design, Tech |
| 0:55–1:30 | **Fair Drop** trực tiếp: commitment → reveal → audit; bot M2M bị chặn ở G2/G4 | Quality, Tech |
| 1:30–1:50 | Chủ quán kéo trần **agent share** xuống 50% → agent nhận `POLICY_DENIED S2` kèm gợi ý gọi quán | Impact |
| 1:50–2:30 | **Biểu đồ pass^k A0 vs A1** + bảng vi phạm + red-team x/12 + false-block rate | Tech, Impact |
| 2:30–2:55 | Kiến trúc: 2 PEP, chuỗi danh tính, dịch vụ AWS | AWS Builder |
| 2:55–3:00 | "Restaurants invite agents in – on their terms." | Impact |

---

## 13. Ánh xạ tiêu chí chấm [S1]

| Tiêu chí | FairTable v2 đáp ứng bằng |
|---|---|
| **Tech Implementation** | MCP 2025-11-25 stateful + Tasks + elicitation (form và URL); Gateway (JWT, interceptor, Policy) + Runtime + Identity; Cedar ở 2 PEP; `TransactWriteItems`; pass^k, C_out |
| **Design** | Voice-first: xác nhận ngay khi nằm trong mandate, duyệt trên điện thoại khi vượt; `spoken_summary`; `next_step` |
| **Potential Impact** | Nhà hàng độc lập ở Mỹ; bối cảnh luật NY; nhà hàng giữ quyền kiểm soát bằng agent share |
| **Quality of the Idea** | Đảo ngược vấn đề: nhà hàng **mời** agent vào kèm luật; xổ số công bằng; ablation chứng minh bằng số |
| **AWS Builder** | Pipeline nhiều dịch vụ: Bedrock + AgentCore (Runtime, Gateway, Policy, Identity, Evaluations) + Strands |
| **+10% friction log** | Ghi trong lúc làm, nhất là các chỗ về interceptor, MCP target OAuth, Cedar schema, Tasks |

---

## 14. Rủi ro & câu hỏi giám khảo

| Rủi ro | Giảm thiểu |
|---|---|
| Quên bật `passRequestHeaders` → interceptor không thấy token | Checklist cấu hình + test tích hợp đầu tiên [P25] |
| Token M2M thiếu claim | Trigger V3 + `has`-guard (mục 6.1) |
| FastMCP 4.x mới ra, dễ vỡ | Ghim 3.4.7; chỉ nâng sau hackathon |
| -32042 không còn ở spec 2026-07-28 | Bám 2025-11-25; ghi rõ trong README |
| Schema Cedar của AgentCore Policy chưa rõ ❓ | Fallback: luật G chạy trong cedarpy |
| Chi phí eval sát credit | Budgets + nhịp chạy ở mục 9.6 |
| Một mình quá tải | Must/Should/Could + 5 mốc fallback |

| Câu hỏi khó | Trả lời |
|---|---|
| "Sao không dùng OpenTable/Resy?" | Resy không cho agent chưa duyệt [S20]; quán độc lập cần kênh riêng; luật NY yêu cầu thỏa thuận với nhà hàng [P16] |
| "Khác gì một MCP đặt bàn bình thường?" | Biểu đồ **A0 vs A1**: cùng pass^k trên task hợp lệ, nhưng vi phạm và red-team khác hẳn |
| "Làm sao biết đúng người đang đặt?" | Account linking PKCE → interceptor → server xác minh lại token; elicitation gắn với danh tính [P30] |
| "Xổ số có gian lận không?" | Commit–reveal + audit công khai [P8] |
| "Agent tính sai phí thì sao?" | Agent không tính phí; server tính; Automated Reasoning kiểm câu tóm tắt luật |
| "Số độ tin cậy có đáng tin?" | Ghi rõ số task, k, 2 simulator, C_out; thừa nhận simulator có sai lệch [P5] |

---

## 15. Câu hỏi gửi BTC

1. MCP server trên AgentCore Runtime, đứng sau Gateway (MCP target, có interceptor) có được tính là "self-hosted" không?
2. Dùng MCP Tasks (thử nghiệm trong 2025-11-25) có được chấp nhận không?
3. MCP server + client web tự làm được chấm theo đường MCP hay "simulated experience"?
4. MCP Apps render trong client giả lập có được tính cho mục "MCP Apps" không?
5. Demo bot M2M tấn công sandbox của chính mình có vấn đề gì không?

---

## 16. Nguồn ([Px])

Nguồn [S1]–[S74] nằm trong `research-alexa-plus-round3-2026-09.md`. **[AFD]** = file `agent-front-door-architecture.drawio` do bạn cung cấp.

### Giữ từ v1
| ID | Nguồn | Loại | URL |
|---|---|---|---|
| P1 | Design Patterns for Securing LLM Agents against Prompt Injections (arXiv 2506.08837) | G | https://arxiv.org/abs/2506.08837 |
| P2 | Simon Willison – tóm tắt P1 | T | https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/ |
| P3 | Agentic Context Engineering – ACE (arXiv 2510.04618, ICLR 2026) | G | https://arxiv.org/abs/2510.04618 |
| P4 | τ²-bench (arXiv 2506.07982) | G | https://arxiv.org/abs/2506.07982 |
| P5 | Lost in Simulation (arXiv 2601.17087) | G | https://arxiv.org/abs/2601.17087 |
| P6 | Simulated Customers Never Walk Away (arXiv 2606.20708) | G | https://arxiv.org/pdf/2606.20708 |
| P7 | Beyond Cooperative Simulators (arXiv 2605.12894) | G | https://arxiv.org/pdf/2605.12894 |
| P8 | Screening with tolls and damages (arXiv 2508.04456) | G | https://arxiv.org/pdf/2508.04456 |
| P9 | Lottery or waiting-line auction? (J. Public Economics, 2001) | G | https://www.sciencedirect.com/science/article/abs/pii/S0047272701001967 |
| P11 | IETF draft – Attenuating Authorization Tokens for Agentic Delegation Chains | G (draft) | https://datatracker.ietf.org/doc/html/draft-niyikiza-oauth-attenuating-agent-tokens-00 |
| P12 | IETF draft – Credential Delegation for AI Agents (07/2026) | G (draft) | https://www.ietf.org/archive/id/draft-sweeney-wimse-credential-delegation-00.html |
| P14 | NY Governor – ký Restaurant Reservation Anti-Piracy Act (19/12/2024) | G | https://www.governor.ny.gov/news/bon-appetit-governor-hochul-signs-legislation-cracking-down-black-market-restaurant |
| P15 | NY Senate – Bill S9365A | G | https://www.nysenate.gov/legislation/bills/2023/S9365/amendment/A |
| P16 | Holland & Knight – New York Curbs Scalping of Restaurant Reservations | T | https://www.hklaw.com/en/insights/publications/2025/02/new-york-curbs-scalping-of-restaurant-reservations |
| P17 | MCP spec 2025-11-25 – Tasks | G | https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks |
| P18 | FastMCP v2.14.0 release (`task=True`) | G | https://github.com/jlowin/fastmcp/releases/tag/v2.14.0 |
| P19 | Strands – MCP Tasks config | G | https://strandsagents.com/docs/api/python/strands.tools.mcp.mcp_tasks/ |
| P21 | Anthropic – Writing effective tools for agents (đọc qua bản tóm tắt) | G/T | https://www.anthropic.com/engineering/writing-tools-for-agents |
| P22 | ARMO – phần dư của các design pattern | T | https://www.armosec.io/blog/design-patterns-for-securing-llm-agents/ |
| P23 | jgraph/drawio – Sidebar-AWS4.js | G | https://raw.githubusercontent.com/jgraph/drawio/dev/src/main/webapp/js/diagramly/sidebar/Sidebar-AWS4.js |

### Mới trong v2
| ID | Nguồn | Ngày | Loại | URL |
|---|---|---|---|---|
| P25 | AWS docs – Using interceptors with Gateway (`passRequestHeaders`, tối đa 1 interceptor mỗi loại) | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html |
| P26 | AWS docs – Types of interceptors (payload, streaming, elicitation) | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html |
| P27 | AWS docs – Header propagation with Gateway (allowlist) | 2026 | G | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html |
| P28 | AWS ML Blog – Secure AI agents with Policy and Lambda interceptors | 30/06/2026 | G | https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/ |
| P29 | AWS ML Blog – Fine-grained access control with Gateway interceptors | 2026 | G | https://aws.amazon.com/blogs/machine-learning/apply-fine-grained-access-control-with-bedrock-agentcore-gateway-interceptors/ |
| P30 | MCP spec 2025-11-25 – Elicitation (-32042; gắn elicitation với danh tính) | 2025 | G | https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation |
| P31 | Vercel – MCP elicitation: form mode vs URL mode (-32042 bị bỏ ở 2026-07-28) | 2026 | T | https://vercel.com/i/mcp-elicitation-form-vs-url-mode |
| P32 | pulseengine/mcp PR #81 – lỗi kiểm tra input trả về dạng tool execution error | 2025 | T | https://github.com/pulseengine/mcp/pull/81 |
| P33 | AWS docs – DynamoDB TTL (xóa trong vòng vài ngày; item hết hạn vẫn hiện khi đọc) | 2026 | G | https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html |
| P34 | AWS docs – Cognito pre token generation trigger (V2 user, V3 M2M, Essentials/Plus) | 2026 | G | https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html |
| P35 | Rabanser et al. – Towards a Science of AI Agent Reliability (arXiv 2602.16666, ICML 2026) | 2026 | G | https://arxiv.org/abs/2602.16666 |
| P36 | Normal Tech – tóm tắt P35 (outcome consistency 30–75%) | 24/02/2026 | T | https://www.normaltech.ai/p/new-paper-towards-a-science-of-ai |
| P37 | MCP Apps – overview (sandbox iframe, giao tiếp hai chiều); README ext-apps (gói host `app-bridge`) | 2026 | G / bản mirror | https://modelcontextprotocol.io/extensions/apps/overview · https://github.com/matteo8p/ext-apps |
| P38 | PyPI – fastmcp · mcp · strands-agents · cedarpy · joserfc · mangum (kiểm qua PyPI JSON API ngày 28/09/2026) | 2026 | G | https://pypi.org/project/fastmcp/ · https://pypi.org/project/mcp/ · https://pypi.org/project/strands-agents/ · https://pypi.org/project/cedarpy/ · https://pypi.org/project/joserfc/ · https://pypi.org/project/mangum/ |
| P39 | k9securityio/cedar-py – Python bindings cho Cedar (Apache-2.0) | 09/2026 | G | https://github.com/k9securityio/cedar-py |

---

## 17. Audit trail (v2)

**Đã kiểm chứng trong vòng này:**
- **Luật Cedar PEP-2** chạy bằng `cedarpy` 4.12.1: đúng ở 7 tình huống; annotation `@id` và `@on_deny` giữ nguyên khi xuất JSON.
- **Thử nghiệm `has`-guard:** viết naive → bot được **Allow**; có guard → **Deny**.
- **PyPI:** FastMCP 3.4.7 (bản 3.x cuối), FastMCP 4.0.0 ra 31/08/2026, mcp 1.30.0 (1.x cuối), Strands 1.57.1 (mới nhất); giấy phép FastMCP Apache-2.0, joserfc BSD-3, mangum MIT. `cedarpy` có wheel aarch64 và repo Apache-2.0.
- **Icon draw.io:** kiểm tự động từ `Sidebar-AWS4.js`. Hai icon hỏng của AFD đã sửa: `budgets` → `budgets_2`; `eventbridge_scheduler` dùng đúng shape cấp resource.
- **Diagram:** 0 node chồng lấn; mọi cạnh trỏ tới node có thật; XML hợp lệ.
- **Tài liệu kỹ thuật:** interceptor, header propagation, -32042, TTL, Cognito V2/V3, C_out, AppBridge – mỗi mục đều có nguồn gốc ở trên.

**Vẫn chưa xác minh (❓):**
- Schema entity Cedar của AgentCore Policy cho MCP target.
- `task=True` của FastMCP 3.4.7 khi chạy trên AgentCore Runtime.
- Giá model cụ thể.
- Quyền dùng Nova Act.
- BTC chấp nhận kiến trúc "Runtime + Gateway + interceptor".

**Giả định [Suy luận]:** tool `mandate_status`; tên header `x-ft-user-token`; thứ tự ưu tiên deny > step-up > allow; thiết kế GSI1/GSI2; ước tính chi phí eval; dùng seed làm khóa HMAC; fallback gọi thẳng Runtime.
