# 中国大陆 Web 应用身份体系落地规格：微信扫码 / QQ 扫码 / 邮箱注册

> 调研基准日 2026-08-27。endpoint 与参数逐条取自腾讯官方文档原文，并已实测 `api.weixin.qq.com`、`graph.qq.com` 在线。
> 官方文档未明说的一律标注 **【需核实】**，不做推断填充。

## 0. 结论速览

| 通道 | 主体资质 | 个人开发者 | 建议 |
|---|---|---|---|
| 微信网站应用扫码登录 `snsapi_login` | 开放平台账号（个人/企业/政府/媒体/其他组织均可注册）+ **网站应用审核通过** + **微信登录审核通过** | **未确认**（见 §2.3） | 做成可插拔 provider，先不接 |
| 微信公众号带参二维码扫码关注登录 | **仅「已认证服务号」** 可调 `/cgi-bin/qrcode/create` | **不能**（个人开不了服务号） | 门槛不低于网站应用，仅备选 |
| QQ 互联网站应用登录 | 企业 / 个体户 / **个人** 三类主体均可 | **能**，且**未过审时开发者本人 QQ 号可直接登录调试** | 优先接这条 |
| 邮箱注册 | 无 | 能 | **主账号体系，第一优先级** |

架构决策：**邮箱账号是地基，微信/QQ 是插件**。三表模型（users / identities / sessions）+ `OAuthProvider` Protocol + `MockScanProvider`，资质到位只改环境变量。

---

## 1. 微信网站应用微信登录（OAuth2.0）

官方：<https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html>
新版同内容页：<https://developers.weixin.qq.com/doc/oplatform/developers/dev/auth/web>

### 1.1 前置条件（官方原文）

> 在微信开放平台注册开发者账号，并拥有一个**已审核通过的网站应用**，并获得相应的 AppID 和 AppSecret，**申请微信登录且通过审核后**，可开始接入流程。

授权回调域配置规则（官方）：
- 每个网站应用**最多 1 个**授权回调域名；**每月最多改 5 次**
- 只填域名（`www.qq.com`），**不带 `http://` 协议头**
- **网站应用需审核通过后才可编辑授权回调域配置**
- 三种验证模式：仅域名模式 / 仅地址模式（`https://www.qq.com/callback`）/ 兼容模式

### 1.2 Step 1 — 请求 CODE

```
GET https://open.weixin.qq.com/connect/qrconnect?appid=APPID&redirect_uri=REDIRECT_URI&response_type=code&scope=snsapi_login&state=STATE&lang=cn#wechat_redirect
```

| 参数 | 必须 | 说明 |
|---|---|---|
| `appid` | 是 | 应用唯一标识 |
| `redirect_uri` | 是 | 请使用 urlEncode 处理；域名须与审核时的授权回调域一致 |
| `response_type` | 是 | 固定 `code` |
| `scope` | 是 | 网页应用**目前仅填 `snsapi_login`** |
| `state` | 否 | 原样带回，防 CSRF；建议「简单随机数 + session 校验」 |
| `lang` | 否 | `cn`（默认）/ `en` |

- `#wechat_redirect` 锚点**必须保留**
- 成功回跳：`redirect_uri?code=CODE&state=STATE`
- **用户禁止授权则不会发生重定向**（前端必须有超时兜底）
- `code` 有效期 **10 分钟**，**只能成功换取一次 access_token 即失效**

内嵌二维码 JS：`https://res.wx.qq.com/connect/zh_CN/htmledition/js/wxLogin.js`（实测 200）

```javascript
new WxLogin({
  self_redirect: true,   // true=iframe 内跳转(需父页轮询)，false=top window 跳转
  id: "login_container", // 必填，容器 id
  appid: "", scope: "snsapi_login",
  redirect_uri: "",      // 必填，需 UrlEncode
  state: "",
  style: "black",        // black(默认) | white
  href: "",      // 自定义 CSS；stylelite=1 时失效
  stylelite: 1,          // 1=新 UI，扫码区建议预留 220x220px
  fast_login: 1,         // 0=禁用 PC 快速登录
  color_scheme: "auto",  // light | dark | auto
  onReady(ok) {}, onQRcodeReady() {}
});
```

**Chrome 142+ 陷阱（官方原文）**：自行嵌 iframe 时必须加 `allow="local-network-access"`，否则浏览器弹窗拦截。用官方 `wxLogin.js` 则无需处理。

### 1.3 Step 2 — code 换 access_token

```
GET https://api.weixin.qq.com/sns/oauth2/access_token?appid=APPID&secret=SECRET&code=CODE&grant_type=authorization_code
```

| 参数 | 必须 | 说明 |
|---|---|---|
| `appid` | 是 | 应用唯一标识 |
| `secret` | 是 | AppSecret |
| `code` | 是 | Step 1 拿到的 code |
| `grant_type` | 是 | `authorization_code` |

返回：

```json
{"access_token":"...","expires_in":7200,"refresh_token":"...",
 "openid":"OPENID","scope":"snsapi_login","unionid":"o6_bmasdasdsad6_2sgVt7hMZOPfL"}
```

| 字段 | 说明 |
|---|---|
| `access_token` | 有效期 **2 小时** |
| `expires_in` | 秒 |
| `refresh_token` | 有效期 **30 天**，无法续期 |
| `openid` | 授权用户唯一标识（用户 + AppID） |
| `scope` | 已授权作用域，逗号分隔 |
| `unionid` | 用户统一标识。新版文档：**「当且仅当该网站应用已获得该用户的 userinfo 授权时，才会出现该字段」** |

错误：`{"errcode":40029,"errmsg":"invalid code"}`；实测无效 appid → `{"errcode":40013,"errmsg":"invalid appid, rid: ..."}`

### 1.4 刷新 / 校验

```
GET https://api.weixin.qq.com/sns/oauth2/refresh_token?appid=APPID&grant_type=refresh_token&refresh_token=REFRESH_TOKEN
GET https://api.weixin.qq.com/sns/auth?access_token=ACCESS_TOKEN&openid=OPENID
```

- refresh 语义：token 已超时 → 换新的；未超时 → token 不变但**超时时间刷新（续期）**
- 失败：`{"errcode":40030,"errmsg":"invalid refresh_token"}` / `{"errcode":40003,"errmsg":"invalid openid"}`

### 1.5 Step 3 — 获取用户信息

```
GET https://api.weixin.qq.com/sns/userinfo?access_token=ACCESS_TOKEN&openid=OPENID&lang=zh_CN
```

| 参数 | 必须 | 说明 |
|---|---|---|
| `access_token` | 是 | 调用凭证 |
| `openid` | 是 | 普通用户标识 |
| `lang` | 否 | `zh_CN` / `zh_TW` / `en`，**默认 `en`** |

返回：

```json
{"openid":"OPENID","nickname":"NICKNAME","sex":1,"province":"","city":"","country":"CN",
 "headimgurl":"https://thirdwx.qlogo.cn/mmopen/.../0","privilege":[],"unionid":"..."}
```

| 字段 | 可用性 |
|---|---|
| `openid` | 可用 |
| `nickname` | 可用 |
| `headimgurl` | 可用；末位数值为尺寸（0/46/64/96/132，0 = 640×640） |
| `unionid` | 可用 |
| `sex` / `province` / `city` / `country` | **不可用** — 官方：Open 平台授权接口**不再返回用户性别及地区**，2021-10-20 24 时生效 |

**两个必踩的坑（官方原文）**：
1. 不再返回性别/地区（同上）
2. **「在用户修改微信头像后，旧的微信头像 URL 将会失效」** → 拿到后必须自行下载落地保存

作用域 ↔ 接口对照：`snsapi_base` → `/sns/oauth2/access_token`、`/sns/oauth2/refresh_token`、`/sns/auth`；`snsapi_userinfo` → `/sns/userinfo`

### 1.6 频率限制与错误码（官方）

| 接口 | 频率限制 |
|---|---|
| code 换 access_token | 1 万 / 分钟 |
| 刷新 access_token | 5 万 / 分钟 |
| 获取用户基本信息 | 5 万 / 分钟 |

常见错误码：`40029` invalid code · `40030` invalid refresh_token · `40003` invalid openid · `10003` redirect_uri 域名与后台配置不一致 · `10005` 此账号并没有这些 scope 的权限

官方排障页明确：**「网站应用才支持扫码登录，服务号是不支持的」**、**「网站应用扫码登录（需使用网站应用账号）需填写 `snsapi_login`」**

### 1.7 UnionID 机制

官方速记公式：

```
微信用户 + AppID     = openid
微信用户 + 开放平台账号 = unionid
```

- 只要 AppID 不变，openid 不变；只要绑定的开放平台账号不变，unionid 不变
- 覆盖范围：移动应用、网站应用、小程序、小游戏、公众号、服务号、微信小店、小店联盟带货机构、小店带货助手
- 公众号网页授权侧：unionid **仅当 `scope=snsapi_userinfo`** 且**已在开放平台绑定服务号**时返回
- **代码必须容忍 `unionid` 缺失**，回落到 `(provider, subject=openid)`

---

## 2. 微信主体资质：明确结论 + 明确的「需核实」

### 2.1 官方文档能确证的事实

来源：《注册开放平台》<https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/operation/open/create.html>

1. **注册流程**：邮箱注册 → 邮箱激活 → **登记主体信息** → 确认主体信息 → **完成开发者资质认证**（路径：微信开放平台 → 账号管理 → 开发者资质认证）
2. **主体类型**：官方文档给出 5 类登记页截图 —— **政府 / 媒体 / 企业 / 其他组织 / 个人**。→ **个人可以注册微信开放平台账号，这一点是确定的。**
3. **未认证账号的限制**（官方原文，仅这三条）：
   - 只可创建 **10 个移动应用**
 - 只可创建 **10 个网页应用**
   - 不支持通过控制台绑定公众号
4. **资质认证解锁高级能力** —— 直接证据：《网站应用》平台功能页中「PC 小程序插件」的**申请前置条件**写死为「网站应用已审核通过」+「**网站应用所属的开放平台账号已完成开发者资质认证**」；《配置网站应用业务域名》开篇亦为「**对于已通过认证的开放平台账号**，其网站应用需在登记业务域名并通过审核」。
5. **邮箱限制**：注册邮箱须未被微信开放平台注册、未被微信公众平台注册、未被微信私人账号绑定。

### 2.2 明确结论（一句话）

> **个人可以注册微信开放平台账号并创建网页应用（≤10 个）；但 `snsapi_login` 的硬前置是「网站应用审核通过 + 微信登录审核通过」，而开放平台的高级能力被官方明确挂在「开发者资质认证」之下。因此「个人主体能否最终拿到微信扫码登录」未获官方文档确证，必须实测。**

### 2.3 需核实（务必自查，不要采信任何二手资料）

| # | 待核实项 | 核实方法 |
|---|---|---|
| A | **`snsapi_login` 是否强制要求「开发者资质认证」** | 官方「未认证账号的限制」只有三条，未列微信登录。登录 open.weixin.qq.com → 管理中心 → 创建网站应用 → 看「微信登录」能力是否标注需资质认证 |
| B | **个人主体能否通过「开发者资质认证」** | 账号管理 → 开发者资质认证 → 查看主体类型下拉是否含「个人」 |
| C | **认证费用** | 第三方口径一致为「中国大陆 300 元 / 非中国大陆 99 美元，有效期一年，最后三个月可年审续期」，但 open.weixin.qq.com 对应页面需登录态，**本次未取得官方公开出处**。以控制台实时显示为准 |
| D | **授权回调域是否要求 ICP 备案** | 官方只对**业务域名**（PC OpenSDK 用）明写「域名需经过 ICP 备案，新备案域名需 24 小时后才可配置」；授权回调域文档未提备案。需控制台实测 |

---

## 3. 替代方案：微信公众号带参二维码扫码关注登录

### 3.1 流程

```
① 后端 GET /cgi-bin/token 拿 access_token（或 /cgi-bin/stable_token）
② 生成 state，POST /cgi-bin/qrcode/create（scene_str = state），拿 ticket
③ GET https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=TICKET 渲染二维码
④ 用户扫码 → 微信 POST XML 事件到你配置的服务器 URL
   · 未关注→关注：Event=subscribe，EventKey=qrscene_<scene>，Ticket
   · 已关注→扫码：Event=SCAN，      EventKey=<scene>，        Ticket
⑤ 后端用 FromUserName(openid) 落库，把 state 置为 confirmed
⑥ 前端轮询发现 confirmed → 换会话
```

### 3.2 生成带参二维码

```
POST https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token=ACCESS_TOKEN
{"expire_seconds":300,"action_name":"QR_STR_SCENE","action_info":{"scene":{"scene_str":"<state>"}}}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `expire_seconds` | number | 否 | 秒，**最大 2592000（30 天）**，仅临时二维码需要 |
| `action_name` | string | 是 | `QR_SCENE`(临时整型) / `QR_STR_SCENE`(临时字符串) / `QR_LIMIT_SCENE`(永久整型) / `QR_LIMIT_STR_SCENE`(永久字符串) |
| `action_info.scene.scene_id` | number | 否 | 临时为 32 位非 0 整型；永久最大 100000 |
| `action_info.scene.scene_str` | string | 否 | **长度 1–64** |

返回 `ticket` / `expire_seconds` / `url`。换图：`GET https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=TICKET`（官方：**本接口无须登录态即可调用**；**TICKET 记得 UrlEncode**；成功 200 + `image/jpg`，ticket 非法 404）。

**数量限制**：永久二维码**最多 10 万个** → 登录场景必须用**临时**二维码（`QR_STR_SCENE` + `expire_seconds=300`）。

错误码：`-1` system error · `40001` invalid credential · `40052` invalid action name · `40053` invalid action info

### 3.3 事件推送报文

```xml
<!-- 未关注 → 关注 -->
<xml><ToUserName><![CDATA[toUser]]></ToUserName>
 <FromUserName><![CDATA[FromUser]]></FromUserName><CreateTime>123456789</CreateTime>
 <MsgType><![CDATA[event]]></MsgType><Event><![CDATA[subscribe]]></Event>
 <EventKey><![CDATA[qrscene_123123]]></EventKey><Ticket><![CDATA[TICKET]]></Ticket></xml>

<!-- 已关注 → 扫码：Event=SCAN，EventKey 无 qrscene_ 前缀 -->
```

解析时必须 `event_key.removeprefix("qrscene_")`，且**两种事件都要处理**，否则老粉丝登不上。

可靠性约定（官方原文）：
- **五秒内收不到响应会断掉连接并重新发起请求，总共重试三次**
- 排重推荐 **FromUserName + CreateTime**
- 无法保证 5 秒内处理完 → **可以直接回复空串**，微信不会重试

→ 登录事件处理器**同步只做「写库 + 置 state」，立刻 `return ""`**，其余丢后台任务。

隐私合规（官方原文）：收到 **unsubscribe** 事件时**需要删除该用户的所有信息** → `identities` 表必须有对应删除路径。

### 3.4 资质差异（关键）

| 项 | 网站应用扫码登录 | 公众号带参二维码 |
|---|---|---|
| 账号类型 | 开放平台「网站应用」 | **已认证服务号** — `createQRCode` 官方「适用范围」原文：**「本接口支持『服务号（仅认证）』账号类型调用。其他账号类型如无特殊说明，均不可调用。」** |
| 配套网页授权 | 不适用 | 官方：「网页授权**支持已认证的服务号**使用，其他类型的账号…均不支持」；特殊补充：已认证的政府、事业单位和媒体类型的公众号也有权限 |
| 主体 | 个人可注册账号（能否过资质认证见 §2.3） | 服务号不面向个人主体开放 → **个人开发者此路不通** |
| 额外收益 | 无 | 用户成为粉丝，可发模板消息/客服消息 |

> **结论：公众号路线不是「资质降级方案」，门槛只高不低。** 它唯一的价值是：如果你**已经**有认证服务号，就能跳过「网站应用审核 + 微信登录审核」，并顺带完成粉丝沉淀。对个人开发者无意义。

---

## 4. QQ 互联网站应用登录（OAuth2.0 server-side）

官方 wiki：<https://wiki.connect.qq.com/使用Authorization_Code获取Access_Token>

> ⚠️ wiki.connect.qq.com 页脚为「© 1998 - 2013 Tencent」，正文仍提及「腾讯朋友 / 朋友网」等已下线产品，**内容陈旧**。以下 endpoint 与参数为文档原文，且已实测 `graph.qq.com` 在线（`GET /oauth2.0/me?access_token=invalid&fmt=json` → `{"error":100013,"error_description":"access token is illegal"}`），但控制台 UI 行为以实际为准。

### 4.1 Step 1 — 获取 Authorization Code

```
GET https://graph.qq.com/oauth2.0/authorize
```

| 参数 | 必须 | 含义 |
|---|---|---|
| `response_type` | 必须 | 固定 `code` |
| `client_id` | 必须 | 申请 QQ 登录成功后分配的 **appid** |
| `redirect_uri` | 必须 | 必须是注册 appid 时填写的**主域名下**的地址，需 URLEncode |
| `state` | **必须** | 官方标注为「必须」。原文：「用于第三方应用防止 CSRF 攻击，成功授权后回调时会原样带回。**请务必严格按照流程检查用户与 state 参数状态的绑定**」 |
| `scope` | 可选 | 接口名列表，逗号分隔（如 `get_user_info,list_album`）；不传默认 `get_user_info`。官方建议「只传入必要的接口名称」 |
| `display` | 可选 | 仅 PC 网站接入时使用；传 `mobile` 展示移动端样式 |

回跳：`http://your.site/cb?code=9A5F...06AF&state=test`，**code 10 分钟内过期**。用户取消登录时 PC 网站登录页直接关闭（无回调）。

两个官方明写的限制：
- **「非 qq.com 域接入互联登录，如果用 iframe 会导致无法成功携带登录态信息」**
- **「APP 内嵌的 H5 场景使用 QQ 登录，这种场景互联本身是不支持的」**

### 4.2 Step 2 — code 换 Access Token

```
GET https://graph.qq.com/oauth2.0/token
```

| 参数 | 必须 | 含义 |
|---|---|---|
| `grant_type` | 必须 | `authorization_code` |
| `client_id` | 必须 | appid |
| `client_secret` | 必须 | appkey |
| `code` | 必须 | 上一步的 code（10 分钟过期） |
| `redirect_uri` | 必须 | 与上一步一致（移动端 app 可不填） |
| `fmt` | 可选 | **官方原文：「因历史原因，默认是 x-www-form-urlencoded 格式，如果填写 json，则返回 json 格式」** |
| `need_openid` | 可选 | **`need_openid=1` 表示同时获取 openid** —— 可省掉一次 `/oauth2.0/me` 调用 |

默认返回（不指定 fmt，**不是 JSON**）：

```
access_token=FE04************CCE2&expires_in=5184000&refresh_token=88E4************BE14
```

> **必踩坑：一律显式带 `fmt=json`。**

`access_token` 有效期 **60 天**（样例 `expires_in=5184000`）。

### 4.3 Step 3（可选）— 权限自动续期

```
GET https://graph.qq.com/oauth2.0/token?grant_type=refresh_token&client_id=&client_secret=&refresh_token=&fmt=json
```

官方原文：**「refresh_token 仅一次有效」**；「每次生成最新的 refresh_token，且仅一次有效，一次登录，refresh_token 整个续票过程，**最长有效期：3 个月**」。

### 4.4 获取 OpenID

```
GET https://graph.qq.com/oauth2.0/me?access_token=ACCESSTOKEN[&fmt=json]
```

| 参数 | 必须 | 说明 |
|---|---|---|
| `access_token` | 必须 | Step 2 拿到的 token |
| `fmt` | 可选 | **官方原文：「因历史原因，默认是 jsonpb 格式，如果填写 json，则返回 json 格式」** |

默认（jsonp 包裹）：`callback( {"client_id":"YOUR_APPID","openid":"YOUR_OPENID"} );`
加 `fmt=json` 后为纯 JSON（**已实测确认**）。

### 4.5 UnionID

```
GET https://graph.qq.com/oauth2.0/me?access_token=ACCESSTOKEN&unionid=1[&fmt=json]
```

返回 `{"client_id":"...","openid":"...","unionid":"..."}`

| 错误码 | 描述 | 说明 |
|---|---|---|
| `100016` | access token check failed | 用户凭据过期（60 天）或者不正确 |
| `100048` | companyid not set | **未申请 unionID 接口调用权限** |

官方注意事项：
- 「开发者应该注意保存 openID、unionID 信息」
- **「同一开发者名下最多支持 60 个应用进行 UnionID 打通」**
- **「unionID 至少是 36 个字节长度，建议开发者预留 64 字节存储空间」**

申请入口（官方指引）：登录 connect.qq.com → 应用管理 → 对目标应用【查看】（**该应用审核状态必须为「通过」**）→【应用接口】→ Unionid 一栏【申请】→ 等待审核。
**「通过 QQ 互联邮箱渠道申请的打通业务，将于 2019 年 9 月 2 日停止服务」** → 只能走官网自助申请。

### 4.6 获取用户信息

```
GET https://graph.qq.com/user/get_user_info?access_token=&oauth_consumer_key=APPID&openid=
```

返回字段：`ret`、`msg`、`is_lost`、`nickname`、`figureurl`(30×30)、`figureurl_1`(50×50)、`figureurl_2`(100×100)、`figureurl_qq_1`(40×40)、`figureurl_qq_2`(100×100)、`gender`、`gender_type`、`province`、`city`、`year`、`constellation`、`is_yellow_vip`、`yellow_vip_level`、`is_yellow_year_vip`。

`ret=0` 为成功；`{"ret":1002,"msg":"请先登录"}` 为典型失败。

**两个坑**：
1. wiki 明写「**注：以下标红返回参数非真实数据**」并链向《【QQ互联】个人隐私保护改造》→ **`gender` / `province` / `city` / `year` 等人口属性可能是脱敏假数据，业务绝不可依赖**。官方还注明 `gender`「如果获取不到则默认返回『男』」、`gender_type`「默认返回 2」。
2. 「**不是所有的用户都拥有 QQ 的 100x100 的头像，但 40x40 像素则是一定会有**」→ 头像取 `figureurl_qq_1` 最稳。

---

## 5. QQ 主体资质与当前可申请状态

### 5.1 现状：仍然开放

- `connect.qq.com` 已改版为「**AI 开发者管理平台 - QQ互联**」，首页描述「为开发者提供 **AI 互联、移动应用、网站应用**三大核心能力」
- QQ 开放平台（q.qq.com）《平台入驻文档》官方原文：「QQ 开放平台…核心为开发者提供游戏社区服务、机器人、小程序、**QQ 互联**等能力支持，同时提供统一的入驻流程与资质认证服务」
- 官方邮箱：`qq_open@tencent.com`

### 5.2 主体资质：**个人可以**

q.qq.com/wiki《注册开放平台所需材料》官方表格：

| 入驻类型 | 企业/个体户 | **个人** |
|---|---|---|
| 账号材料 | 邮箱（建议公共/企业邮箱）、超管身份证号、超管手机号、超管 QQ 号 | 邮箱、超管身份证号、超管手机号、超管 QQ 号 |
| 主体材料 | 有效期内的营业执照 | **个人身份证号 + 个人手机号** |
| 验证材料 | 法人/经营者人脸识别 **或** 企业对公账号打款（二选一） | **个人人脸识别** |

wiki.connect.qq.com《成为开发者》亦写：「在注册页面按要求提交**公司或个人**的基本资料」。

> **明确结论：QQ 互联接受个人主体注册。** 个人走人脸识别即可，不涉及对公打款的冻结风险（官方：对公打款 2 次机会，用完且校验不通过「该账号将被冻结，不再允许注册 QQ 开放平台」）。

### 5.3 审核与 ICP 备案

《应用审核规范》官方要点：
- **备案（硬要求）**：「提供的网站地址及回调地址需在**工信部完成备案**，在 QQ 互联平台填写的备案信息需与工信部保持一致」（§1.5 与 §5.6 重复强调）
- **例外（官方 FAQ #7）**：「我的网站在海外，没有 ICP 运营许可证号，可以申请吗？**可以。**」
- **UI 规范**：必须按腾讯 UI 规范放置「QQ 登录」按钮，图标不允许修改；文字须含「QQ登录」「QQ」「登录」字样
- **禁止项**：「**禁止应用要求用户填写单独的密码**」「不能强制用户填写 QQ 邮箱」「保证用户在输入 QQ 账号并登录后，享有与应用注册用户同等权限」
- **不合作类目**：「**在线游戏应用暂不合作**」
- 域名验证：把验证代码加到网站 `<head>` 标签中；不允许使用跳转域名

### 5.4 ⭐ 开发期最大利好：未过审也能跑通

《申请相关问题》官方 FAQ：

> **Q2**：需要通过审核。**创建应用后便可以立即获取 QQ 登录相关的 appkey 和 appid**。审核过程大约 5 个工作日，**未审核通过的 appid 只能使用注册的 QQ 号码进行测试登录**，审核通过的可以全量使用。
>
> **Q3**：QQ 互联平台对审核未通过的第三方应用采取「**仅开发者帐号能登录**」的限制。

> **注册 → 创建应用 → 立刻拿到 appid/appkey → 用你自己的 QQ 号就能把完整 OAuth 链路真机跑通，不必等审核。三条通道里唯一能做到这点的。**

### 5.5 【需核实】审核时长口径不一致

- 《申请相关问题》FAQ Q2：「审核过程**大约 5 个工作日**」
- 《应用审核规范》§3.2 / §4：「QQ 互联审核团队进行 QQ 登录功能和网站审核（**1-3 个工作日**）」

两处官方页面自相矛盾 → 以控制台提交后的实际反馈为准。

---

## 6. Python 生态推荐（含包名 + 版本，2026-08-27 PyPI 实测）

### 6.1 密码哈希 — ✅ `argon2-cffi>=25.1.0`

```
argon2-cffi>=25.1.0     # 25.1.0 (2025-06-03)，Production/Stable，支持到 Py3.14
```

```python
from argon2 import PasswordHasher
from argon2.profiles import RFC_9106_LOW_MEMORY   # t=3, m=65536(64MiB), p=4, salt16, hash32

ph = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
h  = ph.hash(password)
ph.verify(h, password)          # 失败抛 VerifyMismatchError
if ph.check_needs_rehash(h): ...    # 在线参数升级
```

选型依据：
- **OWASP Password Storage**：Argon2id **最低** m=19456(19MiB), t=2, p=1；bcrypt 仅限遗留系统，work factor ≥10 且**密码上限 72 字节**；PBKDF2-HMAC-SHA256 需 600,000 次；「计算一次 hash 应少于 1 秒」
- **RFC 9106 §4**：FIRST = Argon2id t=1,p=4,m=2^21(2GiB)；**SECOND = Argon2id t=3,p=4,m=2^16(64MiB)**
- `argon2-cffi` 的 `get_default_parameters()` 自 25.1.0 起就返回 `RFC_9106_LOW_MEMORY`

容器内存 <512MiB 时降到 OWASP 下限 `m=19456, t=2, p=1`。

### 6.2 passlib 现状（一句话）

> **passlib 事实停维：最后一版 1.7.4 发布于 2020-10-08（距今 5 年 10 个月），官方 issue #187《Maintenance status?》至今无维护者回应，且 pwdlib README 明确「Starting Python 3.13, passlib won't work anymore」——新项目禁止使用。**

替代：只要 Argon2id → `argon2-cffi`；需要多算法/迁移抽象层 → `pwdlib[argon2]>=0.3.1`（作者自述「not designed to be a complete replacement for passlib」）；必须兼容既有 bcrypt 哈希 → `bcrypt>=5.0.0`。

### 6.3 JWT — ✅ `PyJWT>=2.13.0`（版本下限是硬要求）

```
PyJWT>=2.13.0      # 2.13.0 (2026-05-21)
```

2026-06-15 PyJWT 一次性披露 5 个漏洞，**全部在 2.13.0 修复**：

| CVE | 影响范围 | 摘要 |
|---|---|---|
| CVE-2026-48522 | 2.0.0 → <2.13.0 | PyJWKClient 缺 scheme allowlist，`file://`/`ftp://`/`data:` 致 SSRF + token 伪造 |
| CVE-2026-48523 | 2.9.0 → <2.13.0 | 用 `PyJWK`/`PyJWKClient` 解码时算法白名单绕过 |
| CVE-2026-48524 | 2.0.0 → <2.13.0 | 攻击者控制 `kid` 触发无界 JWKS 请求（DoS） |
| CVE-2026-48525 | 2.8.0 → <2.13.0 | `b64=false` detached JWS 无界 Base64URL 解码，未认证 DoS |
| CVE-2026-48526 | 全部 → <2.13.0 | 公钥 JWK 被当作 HMAC secret，混用算法族时可伪造 HS256 |

（更早：CVE-2026-32597 未知 `crit` 头，2.12.0 修复。）

**`python-jose` 不推荐**：最新 3.5.0（2025-05-28）；CVE-2024-33663（OpenSSH ECDSA 算法混淆）、CVE-2024-33664（压缩 JWE DoS）均在 3.4.0 修复；仓库 open issues 120；FastAPI 官方教程已从 python-jose 改用 PyJWT。

**`Authlib` 1.7.2**：功能最全但 OSV 上有 12+ 条 CVE（含 2026 年 `alg:none` 绕过 CVE-2026-28802、JWK header injection CVE-2026-27962、1-click 账号接管 CVE-2025-68158）。**本项目是 OAuth Client，微信/QQ 流程用 `httpx` 手写 30 行足够，不引入 Authlib。**

### 6.4 会话 — ⚠️ 不要用 JWT 做主会话

本仓库已有 `itsdangerous>=2.2.0` + Starlette `SessionMiddleware`。建议演进为**服务端会话表**（§7.3），因为 JWT 做不到：密码重置后立刻踢掉所有旧会话、「查看我的登录设备/远程下线」、微信 unsubscribe 后清数据、服务端可控的滑动+绝对过期。

### 6.5 邮件发送

```
aiosmtplib>=5.1.2     # 5.1.2 (2026-06-20)，需 Py>=3.10；配 stdlib email.message.EmailMessage
email-validator>=2.3.0  # 2.3.0 (2025-08-26)，注册时语法 + 域名校验
```

不需要 `fastapi-mail`（薄封装，增加依赖面收益不大）。

| 方案 | 包 / 端点 | 大陆适用性 |
|---|---|---|
| **阿里云邮件推送 DirectMail** ✅ 首选 | SMTP `smtpdm.aliyun.com`，端口 **25 / 80 / 465(SSL)**，亦支持 STARTTLS；API SDK `alibabacloud-dm20151123>=1.11.1` | 大陆节点，最稳 |
| **腾讯云邮件推送 SES** ✅ 备选 | API `ses.tencentcloudapi.com`，Region `ap-guangzhou` / `ap-hongkong`；SDK `tencentcloud-sdk-python-ses>=3.1.135` | 大陆节点 |
| Resend | `resend==2.42.0` | ⚠️ 见下 |
| SendGrid | `sendgrid==6.12.5` | ⚠️ 见下 |

> **【需核实 · 无官方声明】Resend / SendGrid 在中国大陆的可用性。**
> 检索 Resend 官方文档全站（含 `llms.txt` 索引）与 SendGrid 文档，**均未找到关于中国大陆的任何官方声明**，因此不能断言「被封锁」。可验证的工程事实是：① 二者 API 端点与发信 IP 均在境外，从大陆服务器出站属跨境访问，无 SLA 覆盖；② 大陆主流收件方（QQ/163/126/189）对境外发信 IP 段反垃圾策略更严。
> **行动项**：在目标机房实测 —— ① `curl -o /dev/null -w '%{http_code} %{time_total}' https://api.resend.com/` 连续 100 次统计 P95/失败率；② 向 qq.com / 163.com / 126.com / gmail.com 各发 20 封，统计收件箱 vs 垃圾箱 vs 丢失。**任一不达标即降级到阿里云/腾讯云。**

阿里云发信域名配置要点（官方）：
- 新域名需 **SPF、DKIM、DMARC、MX 四项全部验证通过**（老域名为所有权、SPF、MX 三项）
- **SPF 记录只能有一条**，多个出口需合并：`v=spf1 include:spf1.dm.aliyun.com -all`
- 「邮件推送使用的域名请勿使用企业邮箱…**邮件推送建议使用子域名**」（如 `mail.yourdomain.com`）
- 域名一般 4 小时内生效，最迟 48 小时
- **ECS 默认禁用 25 端口** → 部署在阿里云 ECS 上时，不勾 SSL 用 **80**，勾 SSL 用 **465**

### 6.6 可直接追加到 requirements.txt

```
# ── 身份与认证 ──────────────────────────────────────────────
argon2-cffi>=25.1.0 # 密码哈希（Argon2id / RFC 9106 profiles）
PyJWT>=2.13.0   # 仅用于短时效签名；<2.13.0 有 5 个 2026-06 CVE
email-validator>=2.3.0      # 注册时邮箱语法 + 域名校验
# itsdangerous>=2.2.0    # 已在依赖中（SessionMiddleware 签名）

# ── 邮件 ────────────────────────────────────────────────────
aiosmtplib>=5.1.2  # 异步 SMTP
# alibabacloud-dm20151123>=1.11.1        # 阿里云 DirectMail API（二选一）
# tencentcloud-sdk-python-ses>=3.1.135   # 腾讯云 SES API（二选一）

# ── 限流（多实例部署时才需要）───────────────────────────────
# limits>=5.8.0 # 带 Redis 后端的通用限流原语

# ── 明确不引入 ──────────────────────────────────────────────
# passlib     事实停维（1.7.4 / 2020-10-08，Py3.13+ 不工作）
# python-jose    CVE 密集，生态已转向 PyJWT
# Authlib    我们只是 OAuth Client；其 CVE 面过大
```

---

## 7. 统一身份模型：五表 DDL 草案（SQLite 方言）

时间统一为 ISO-8601 UTC 文本（`2026-08-27T03:14:15Z`），与仓库现有风格一致。
SQLite 需 `PRAGMA foreign_keys = ON` 外键才生效；`lower(email)` 表达式索引要求 SQLite ≥ 3.9.0。

### 7.1 users — 账号主体，与登录方式解耦

```sql
CREATE TABLE users (
  id         TEXT PRIMARY KEY,   -- UUIDv4 / ULID。不用自增：避免 /users/1 被枚举
  email      TEXT,   -- 可 NULL：纯扫码注册的用户还没绑邮箱
  email_verified_at   TEXT,        -- NULL = 未验证。未验证不给敏感权限
  password_hash       TEXT,    -- PHC 串 $argon2id$v=19$m=65536,t=3,p=4$...
     -- NULL = 无本地口令（仅社交身份）
  password_algo       TEXT,    -- 'argon2id'；批量 rehash 时按此筛选
  password_updated_at TEXT,
  display_name        TEXT NOT NULL DEFAULT '',
  avatar_url    TEXT NOT NULL DEFAULT '',  -- 自托管副本；微信头像 URL 会失效
  status         TEXT NOT NULL DEFAULT 'active',
  created_at    TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  CHECK (status IN ('active','disabled','deleted')),
  -- 有口令必须有邮箱，否则用户永远无法找回
  CHECK (password_hash IS NULL OR email IS NOT NULL)
);

-- 邮箱大小写不敏感唯一
CREATE UNIQUE INDEX ux_users_email ON users(lower(email)) WHERE email IS NOT NULL;
CREATE INDEX        ix_users_status ON users(status);
```

### 7.2 identities — 一个 user 挂 N 个登录身份

```sql
CREATE TABLE identities (
  id        TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  provider     TEXT NOT NULL,   -- 'email'|'wechat_web'|'wechat_mp'|'qq_web'|'mock'
  provider_family  TEXT NOT NULL,   -- 'local'|'wechat'|'qq'|'mock'
-- ↑ 关键：unionid 的唯一性作用域是「厂商开放平台账号」，不是单个 provider。
    --   wechat_web 与 wechat_mp 共享同一个 unionid。
  subject        TEXT NOT NULL,   -- provider 内主键：openid（微信/QQ）| lower(email)（本地）
  union_key     TEXT,      -- unionid；QQ 官方要求预留 64 字节，无则 NULL

  raw_profile      TEXT NOT NULL DEFAULT '{}',  -- JSON 快照：nickname/headimgurl/…（PG 用 jsonb）
  -- 以下三列只在「确实需要代表用户回调厂商 API」时才存；只做登录则全留 NULL
access_token     TEXT,
  refresh_token    TEXT,
  token_expires_at TEXT,

  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  last_login_at    TEXT,

  CHECK (provider_family IN ('local','wechat','qq','mock'))
);

CREATE UNIQUE INDEX ux_identities_subject     ON identities(provider, subject);
CREATE UNIQUE INDEX ux_identities_union         ON identities(provider_family, union_key)
           WHERE union_key IS NOT NULL;
CREATE UNIQUE INDEX ux_identities_user_provider ON identities(user_id, provider);
CREATE INDEX        ix_identities_user          ON identities(user_id);
```

**账号合并规则（写在服务层，不要靠数据库兜底）**

1. 回调拿到 `ExternalIdentity` → 先按 `(provider, subject)` 查；命中即复用 `user_id`
2. 未命中且 `union_key` 非空 → 按 `(provider_family, union_key)` 查；命中则**新建一条 identity 挂到同一个 user_id**（UnionID 打通多入口的全部意义）
3. 仍未命中且当前请求**已登录** → 绑定到当前 user（「账号设置 → 绑定微信」路径）
4. 仍未命中且未登录 → 新建 user（`email=NULL, password_hash=NULL`），引导补绑邮箱
5. **绝不**用第三方返回的昵称做合并（微信/QQ 都不返回邮箱；QQ 的 province/city/year 可能是脱敏假数据）
6. **解绑保护**：删除某条 identity 前必须校验「该 user 仍至少保留一种可登录方式」，否则 409

### 7.3 sessions — 服务端会话

```sql
CREATE TABLE sessions (
  id           TEXT PRIMARY KEY, -- sha256(session_token)。明文 token 只存在于 cookie
  user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  identity_id         TEXT REFERENCES identities(id) ON DELETE SET NULL,  -- 本次用哪种方式登的
  created_at        TEXT NOT NULL,
  last_seen_at        TEXT NOT NULL,
  expires_at   TEXT NOT NULL,      -- 滑动过期（每次活动续 7 天）
  absolute_expires_at TEXT NOT NULL,      -- 绝对上限（30 天），不可续
  revoked_at    TEXT, -- 改密 / 远程下线时批量写
  ip      TEXT NOT NULL DEFAULT '',
  user_agent          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX ix_sessions_user    ON sessions(user_id) WHERE revoked_at IS NULL;
CREATE INDEX ix_sessions_expires ON sessions(expires_at);
```

Cookie：`Secure; HttpOnly; SameSite=Lax; Path=/`。
用 `Lax` 而非 `Strict`：OAuth 回调是顶层导航 GET，Lax 会带 cookie，Strict 不会。

### 7.4 email_verifications — 注册验证 / 密码重置令牌

```sql
CREATE TABLE email_verifications (
  id          TEXT PRIMARY KEY,
  user_idTEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose     TEXT NOT NULL,          -- 'verify' | 'reset'
  email       TEXT NOT NULL,     -- 冗余：换邮箱场景锁定当时的目标地址
  token_hash  TEXT NOT NULL UNIQUE,   -- sha256(secrets.token_urlsafe(32))，明文只出现在邮件里
  expires_at  TEXT NOT NULL,          -- verify +24h / reset +30min
  used_at     TEXT,      -- 单次使用
  request_ip  TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  CHECK (purpose IN ('verify','reset'))
);

CREATE INDEX ix_email_verifications_live ON email_verifications(user_id, purpose) WHERE used_at IS NULL;
CREATE INDEX ix_email_verifications_gc   ON email_verifications(expires_at);
```

### 7.5 oauth_states — 扫码登录状态机

```sql
CREATE TABLE oauth_states (
  state       TEXT PRIMARY KEY,   -- secrets.token_urlsafe(32)，同时就是 OAuth state 参数
  provider        TEXT NOT NULL,
  status       TEXT NOT NULL,      -- pending|scanned|confirmed|consumed|expired|failed
  binding_hash       TEXT NOT NULL,      -- sha256(下发给浏览器的 httpOnly cookie)，防他人抢兑
  scene  TEXT,      -- 公众号带参二维码 scene_str
  qr_ticket       TEXT,     -- 公众号 ticket
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  session_token_hash TEXT,           -- confirmed 后写入；兑换一次即转 consumed
  redirect_to  TEXT NOT NULL DEFAULT '/',
  error              TEXT,
  created_at         TEXT NOT NULL,
  updated_atTEXT NOT NULL,
  expires_at         TEXT NOT NULL,      -- +5min，与二维码 expire_seconds 对齐
  CHECK (status IN ('pending','scanned','confirmed','consumed','expired','failed'))
);

CREATE INDEX ix_oauth_states_gc ON oauth_states(expires_at);
```

### 7.6 PostgreSQL 迁移差异

| SQLite | PostgreSQL |
|---|---|
| `TEXT` 主键存 UUID | `uuid` + `gen_random_uuid()` |
| `TEXT` 存 ISO8601 | `timestamptz` |
| `TEXT` 存 JSON | `jsonb` |
| 需 `PRAGMA foreign_keys=ON` | 默认生效 |
| `lower(email)` 表达式索引 | 同（或改 `citext` 扩展） |

---

## 8. 可插拔 provider 接口设计草案

### 8.1 Protocol 签名

```python
# src/app/auth/providers/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, runtime_checkable

ProviderFamily = Literal["wechat", "qq", "local", "mock"]
LoginMode = Literal["redirect", "qrcode"]


@dataclass(frozen=True, slots=True)
class AuthzChallenge:
    """发起登录后交给前端的东西：要么一个跳转 URL，要么一张自绘二维码。"""
    state: str
    mode: LoginMode
    redirect_url: str | None = None # mode == "redirect"
    qr_image_url: str | None = None   # mode == "qrcode"，如 showqrcode?ticket=
    qr_content: str | None = None     # mode == "qrcode"，需前端自绘时给内容
  expires_in: int = 300


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """provider 归一化后的身份。字段与 identities 表一一对应。"""
    provider: str
    family: ProviderFamily
    subject: str              # openid
    union_key: str | None = None    # unionid，可能为 None —— 调用方必须容忍
    display_name: str = ""
    avatar_url: str = ""
 raw: Mapping[str, object] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """厂商侧业务错误。code 为厂商原始错误码（微信 errcode / QQ error）。"""

    def __init__(self, provider: str, code: str | int, message: str) -> None:
        super().__init__(f"[{provider}] {code}: {message}")
        self.provider, self.code, self.message = provider, code, message


@runtime_checkable
class OAuthProvider(Protocol):
    name: str    # 'wechat_web' | 'qq_web' | 'wechat_mp' | 'mock'
    family: ProviderFamily
    login_mode: LoginMode
    label: str    # 前端按钮文案：'微信登录'

    def is_configured(self) -> bool:
        """凭据齐备且当前环境允许。返回 False 时该 provider 对前端与路由完全不可见。"""
        ...

    async def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
 """生成挑战。qrcode 模式在此调用厂商建码接口。"""
        ...

    async def exchange(
        self, *, code: str, state: str, redirect_uri: str
    ) -> ExternalIdentity:
        """redirect 模式：code 换 token 换用户信息。qrcode 模式抛 NotImplementedError。"""
        ...

    async def handle_push(
      self, *, body: bytes, query: Mapping[str, str]
    ) -> tuple[str, ExternalIdentity] | None:
   """qrcode 模式（公众号事件推送）：验签 + 解析，返回 (state, identity)。
        非事件类 provider 返回 None。必须在 5 秒内返回（微信超时重试 3 次）。"""
    ...
```

### 8.2 注册表 + 配置驱动

```python
# src/app/auth/providers/registry.py
import os

_REGISTRY: dict[str, OAuthProvider] = {}


def register(p: OAuthProvider) -> None:
    if p.name in _REGISTRY:
   raise ValueError(f"duplicate provider: {p.name}")
    _REGISTRY[p.name] = p


def enabled() -> list[OAuthProvider]:
    """白名单 ∩ 凭据齐备。前端 /api/auth/providers 只吐这个列表。"""
    raw = os.getenv("LOCI_AUTH_PROVIDERS", "email")
    allow = {s.strip() for s in raw.split(",") if s.strip()}
  return [p for name, p in _REGISTRY.items() if name in allow and p.is_configured()]


def get(name: str) -> OAuthProvider:
  for p in enabled():
if p.name == name:
      return p
    raise KeyError(name)   # 路由层转 404 —— 不要泄漏「存在但未配置」
```

环境变量（唯一的开关面）：

```dotenv
# 阶段 0：无任何资质 —— 只有邮箱 + Mock 扫码
LOCI_AUTH_PROVIDERS=email,mock

# 阶段 1：QQ 互联应用创建完成（未过审也能用开发者本人 QQ 号登录）
LOCI_AUTH_PROVIDERS=email,qq_web
LOCI_QQ_WEB_APPID=101xxxxxx
LOCI_QQ_WEB_APPKEY=xxxxxxxx

# 阶段 2：微信资质到位
LOCI_AUTH_PROVIDERS=email,qq_web,wechat_web
LOCI_WECHAT_WEB_APPID=wxxxxxxxxxxxxxxx
LOCI_WECHAT_WEB_SECRET=xxxxxxxx

LOCI_PUBLIC_BASE_URL=https://your.domain   # 构造 redirect_uri / 邮件链接，绝不读 Host 头
```

### 8.3 MockScanProvider — 开发环境真跑通

```python
# src/app/auth/providers/mock.py
import os
from urllib.parse import quote


class MockScanProvider:
  """用真二维码模拟「扫码 → 确认 → 登录」的完整时序。

    二维码内容是本机 URL：{BASE}/auth/mock/confirm?state=<state>
    手机（同局域网）扫开就是一个「确认登录」页，点一下 → 后端把 state 推到 confirmed。
    对前端、对 oauth_states 状态机、对轮询接口来说，与真微信/QQ 完全同构。
    """

    name = "mock"
    family = "mock"
    login_mode = "qrcode"
    label = "模拟扫码（开发）"

  def is_configured(self) -> bool:
        # 生产环境硬关闭。这行是整个方案的安全底线，不要加任何 override 开关。
     return os.getenv("LOCI_ENV", "dev").lower() != "production"

    async def start(self, *, state: str, redirect_uri: str) -> AuthzChallenge:
     base = os.environ["LOCI_PUBLIC_BASE_URL"].rstrip("/")
        return AuthzChallenge(
            state=state,
            mode="qrcode",
            qr_content=f"{base}/auth/mock/confirm?state={quote(state)}",
            expires_in=300,
        )

    async def exchange(self, *, code, state, redirect_uri):
        raise NotImplementedError("mock provider is qrcode-only")

    async def handle_push(self, *, body, query):
   state = query.get("state")
     if not state:
    return None
        openid = query.get("openid") or f"mock_{state[:12]}"
        return state, ExternalIdentity(
    provider="mock", family="mock", subject=openid,
      union_key=f"mockunion_{openid}",   # 顺带把 UnionID 合并逻辑也覆盖到
      display_name="Mock 用户",
        )
```

两条硬约束：
1. `is_configured()` 在 `LOCI_ENV=production` 时返回 `False` —— `enabled()` 是唯一对外出口，mock provider 在生产**根本不会出现在路由和 provider 列表里**
2. 加一条启动自检：`assert not (is_production and any(p.family == "mock" for p in enabled()))`，让配置错误在启动期就炸

### 8.4 契约测试：真假 provider 跑同一套用例

把官方返回样例存成 fixture，用 `httpx.MockTransport` 回放：

```python
# tests/app/auth/fixtures/wechat_web.py —— 均为官方文档原文样例
ACCESS_TOKEN_OK = {"access_token": "ACCESS_TOKEN", "expires_in": 7200,
              "refresh_token": "REFRESH_TOKEN", "openid": "OPENID",
  "scope": "snsapi_login", "unionid": "o6_bmasdasdsad6_2sgVt7hMZOPfL"}
ACCESS_TOKEN_BAD_CODE = {"errcode": 40029, "errmsg": "invalid code"}
USERINFO_OK = {"openid": "OPENID", "nickname": "NICKNAME",
      "headimgurl": "https://thirdwx.qlogo.cn/mmopen/xxx/0",
            "privilege": [], "unionid": "o6_bmasdasdsad6_2sgVt7hMZOPfL"}
USERINFO_NO_UNIONID = {"openid": "OPENID", "nickname": "N", "headimgurl": ""}

# tests/app/auth/fixtures/qq_web.py
TOKEN_FORM = "access_token=FE04CCE2&expires_in=5184000&refresh_token=88E4BE14"  # 默认 form!
TOKEN_JSON = {"access_token": "FE04CCE2", "expires_in": 5184000, "refresh_token": "88E4BE14"}
ME_JSONP = 'callback( {"client_id":"YOUR_APPID","openid":"YOUR_OPENID"} );'      # 默认 jsonpb!
ME_JSON = {"client_id": "APPID", "openid": "OPENID", "unionid": "UNIONID"}
ME_ERR_100048 = {"error": 100048, "error_description": "companyid not set"}
USERINFO_OK = {"ret": 0, "msg": "", "nickname": "Peter",
    "figureurl_qq_1": "http://q.qlogo.cn/qqapp/100312990/DE19/40", "gender": "男"}
```

```python
@pytest.mark.parametrize("provider", all_registered_providers())
class TestProviderContract:
    def test_start_returns_state_bound_challenge(self, provider): ...
    def test_exchange_maps_to_external_identity(self, provider): ...
    def test_missing_unionid_is_tolerated(self, provider): ...  # union_key is None
    def test_vendor_error_raises_ProviderError(self, provider): ... # 40029 / 100016 / 100048
    def test_expired_state_is_rejected(self, provider): ...
    def test_state_can_only_be_consumed_once(self, provider): ...
    def test_not_configured_provider_is_invisible(self, provider): ...
```

### 8.5 资质到位后的切换清单（就这 5 步）

1. 控制台拿 AppID / AppSecret（QQ：appid / appkey）
2. 配置回调域：微信「授权回调域」填**裸域名**（1 个/应用，5 次/月，**需应用审核通过后才可编辑**）；QQ 填注册时的主域名下地址
3. 环境变量加 `LOCI_WECHAT_WEB_APPID/SECRET`，`LOCI_AUTH_PROVIDERS` 追加 `wechat_web`
4. 跑契约测试（用真 fixture，不发真请求）→ 全绿
5. 灰度：先只对内测账号放开该 provider，观察 24h 的 `ProviderError` 分布再全量

> **代码零改动。这就是可插拔设计的全部意义。**

---

## 9. 扫码状态机与前端轮询契约

### 9.1 先分清哪种流程真的需要轮询

| 流程 | 二维码是谁渲染的 | 前端要不要轮询 |
|---|---|---|
| A. 微信 `qrconnect` 整页跳转 | 微信托管的页面 | **不用**。确认后微信 302 回 `redirect_uri?code=&state=` |
| B. 微信 `wxLogin.js` 内嵌 iframe | 微信托管的 iframe | `self_redirect=false` → top window 跳转，同 A，不用轮询；`self_redirect=true` → iframe 内跳转，**父页面需要轮询 state** |
| C. 微信公众号带参二维码 | **你自己**（`showqrcode?ticket=`） | **必须**轮询或 SSE —— 唯一信号是微信推到你后端的 XML 事件 |
| D. QQ `graph.qq.com/oauth2.0/authorize` | 腾讯托管 | **不用**，同 A |

> 只有 B(self_redirect) 和 C 需要 §9。**不要给 A/D 加轮询。**

### 9.2 状态枚举

```python
QrStatus = Literal[
    "pending",     # 二维码已下发，等待扫描
    "scanned",     # 厂商事件已到达（用户已扫，等待手机端确认）
  "confirmed", # 身份已解析并落库，会话已就绪，等待前端兑换
    "consumed",    # 前端已兑换会话，state 作废
    "expired",     # 超过 expires_at
    "failed",      # 厂商返回错误 / 验签失败
]
```

状态迁移（只允许这些边）：

```
pending  ─► scanned ─► confirmed ─► consumed
   │   │           │
   └── expired  └── expired └── expired
   └── failed   └── failed
```

### 9.3 前端轮询契约

**发起：**

```
POST /api/auth/qr/start
     body: {"provider": "wechat_mp" | "mock", "redirect_to": "/"}

200 {
"state":     "V1StGXR8_Z5jdHi6B-myT",   # CSPRNG 32 bytes urlsafe
  "mode":      "qrcode",           # 或 "redirect"
  "qr_image_url": "https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=...",
  "qr_content":   null, # mode=qrcode 时二者至少有一个
  "redirect_url": null, # mode=redirect 时给这个，前端直接跳转
  "expires_in":   300
}
Set-Cookie: qr_bind=<opaque>; HttpOnly; Secure; SameSite=Lax; Max-Age=300
```

**查询（服务端 long-poll）：**

```
GET /api/auth/qr/{state}?wait=25

200 {"status":"pending"}
200 {"status":"scanned"}
200 {"status":"confirmed","redirect_to":"/"}   + Set-Cookie: session=...
200 {"status":"consumed"}
410 {"status":"expired"}
409 {"status":"failed","error":"provider_error"}
```

| 响应字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | 上面 6 个枚举之一 |
| `redirect_to` | string? | 仅 `confirmed` 时返回，前端 `location.replace()` 目标 |
| `error` | string? | 仅 `failed` 时返回，**不含厂商原始报文**（避免信息泄漏） |

服务端实现：`state` 上挂一个 `asyncio.Event`，请求进来后 `await asyncio.wait_for(ev.wait(), timeout=min(wait, 25))`；状态一变立刻返回，超时则返回当前状态。前端拿到响应后立即再发一次。

**为什么不用 SSE：**

| 维度 | long-poll | SSE |
|---|---|---|
| 浏览器连接数上限 | 与普通 XHR 共享，无额外风险 | **非 HTTP/2 下每浏览器 + 域名仅 6 条**（MDN 明确，Chrome/Firefox 均标记 Won't fix）。用户开 7 个标签就挂 |
| 反代配置 | 无需特殊配置 | Nginx 必须 `proxy_buffering off` + 调大 `proxy_read_timeout` |
| 断线恢复 | 天然重试 | 需处理 `Last-Event-ID` |
| 前端代码 | 与仓库现有 `useLivePolling` 同构 | 新引入一套 `EventSource` 生命周期管理 |

> 登录二维码生命周期只有 5 分钟、状态只变 1–2 次 —— **SSE 的长连接优势在这里换不来任何东西，只换来 6 连接上限这个真实故障源。**

**降级链**：`wait` 参数支持不了（某些代理会截断长请求）→ 客户端自动退回 `?wait=0` 的 2 秒定时短轮询。

### 9.4 前端状态机与三条硬规则

```
idle ──[POST /api/auth/qr/start]──► pending（渲染二维码，开始 long-poll）
pending ──scanned──► scanned（UI：「已扫描，请在手机上确认」）
pending/scanned ──confirmed──► 停止轮询 → location.replace(redirect_to)
pending ──5min──► expired（二维码变灰 +「点击刷新」按钮，停止轮询）
any ──网络错误×3──► failed（提供「改用邮箱登录」出口）
```

1. **必须有过期态**。二维码过期还不停轮询 = 慢速自 DDoS
2. **必须有降级出口**。任何扫码失败都要能一键切到邮箱登录
3. **`document.visibilityState === 'hidden'` 时暂停轮询**，可见时立即补一次

### 9.5 安全要点

| 风险 | 对策 |
|---|---|
| 他人猜 state 抢兑会话 | ① `state = secrets.token_urlsafe(32)`；② 下发 state 时同时下发 httpOnly cookie `qr_bind`，兑换时校验 `sha256(cookie) == binding_hash` |
| state 重放 | `confirmed → consumed` 用 `UPDATE ... WHERE state=? AND status='confirmed'` 单语句 CAS，受影响行数为 0 即拒 |
| Session fixation | 兑换成功后 `request.session.clear()` 再写（**本仓库 `/api/auth/login` 已是此写法，照抄**） |
| 二维码钓鱼（诱导受害者扫攻击者的码） | 确认页展示应用名与登录发起地（IP/城市）；`expires_at` 收到 5 分钟 |
| OAuth `state` 未校验 | 回调里 state 查不到 / 已过期 / 已消费 → 一律 400，**不要**继续用 code 换 token |
| 公众号回调伪造 | 校验 `signature = sha1(sorted(token, timestamp, nonce))`；建议开启消息加解密（安全模式） |

---

## 10. 邮箱注册安全要点（5 条）

### 10.1 哈希参数

- 算法：**Argon2id**，参数用 `argon2.profiles.RFC_9106_LOW_MEMORY`（t=3, m=65536 即 64 MiB, p=4, salt 16B, hash 32B）
- 内存紧张（容器 <512 MiB）时降到 OWASP 下限 **m=19456(19 MiB), t=2, p=1**
- OWASP：**计算一次 hash 应少于 1 秒**；`argon2-cffi` 自述默认约 50 ms
- 登录时用 `ph.check_needs_rehash(h)` 做在线参数升级
- bcrypt 仅限遗留兼容：work factor ≥10，**强制 72 字节上限**，且**不要**做 `bcrypt(sha256(pw))` 预哈希（OWASP 明确警告 null byte 截断 + password shucking；若必须预哈希，唯一安全形式是 `bcrypt(base64(hmac-sha384(data:$password, key:$pepper)), $salt, $cost)`，pepper 不入库）
- 密码策略（OWASP / NIST SP 800-63B）：未启用 MFA 时 **<15 字符视为弱**；最大长度 **≥64**；**不设字符组成规则**、**不强制周期改密**、**不静默截断**、允许全 Unicode 与空白；对接 Pwned Passwords 拦截已泄露口令
- **不引入 pepper**：单机部署收益低、运维债高（pepper 泄漏须换，换 pepper 要强制全员改密）

### 10.2 Token 设计

```python
import hashlib, secrets

token    = secrets.token_urlsafe(32)     # 256-bit CSPRNG 熵，URL 安全
token_hash = hashlib.sha256(token.encode()).hexdigest()   # 只有它入库
```

- **为什么用 SHA-256 而非 Argon2 存 token**：token 本身是 256-bit CSPRNG 输出，不存在字典攻击面，慢哈希纯属浪费；快哈希已能防「库被拖走后直接拿明文 token 改密」。（对比：**用户密码低熵，必须慢哈希**。）
- 有效期：**邮箱验证 24 小时；密码重置 30 分钟**
- **单次使用**：`used_at` 一旦写入即失效；同一 `(user_id, purpose)` 发新 token 时把旧的全部作废
- **绝不**使用自增 ID / 时间戳 / 邮箱派生的 token
- 重置链接的 base URL **必须来自配置**（`LOCI_PUBLIC_BASE_URL`），**绝不读 `request.headers["host"]`** —— OWASP 明确点名 Host Header Injection
- 重置落地页加 `Referrer-Policy: no-referrer`，防 token 经 Referer 泄漏给第三方资源
- 重置成功后：发「密码已被重置」通知邮件（**邮件里绝不含新密码**）；**不要自动登录**；自动或询问后失效该用户**所有**既有会话（`UPDATE sessions SET revoked_at=? WHERE user_id=?`）
- 不推荐用 JWT 做重置 token：无状态意味着无法在服务端单次作废，还得再加黑名单表，白白复杂化

### 10.3 防枚举

三个入口统一返回**通用**响应：

| 场景 | ❌ 错误 | ✅ 正确 |
|---|---|---|
| 登录 | 「invalid password」/「account disabled」 | **「Login failed; Invalid user ID or password.」** |
| 找回密码 | 「This email address doesn't exist in our database.」 | **「If that email address is in our database, we will send you an email to reset your password.」** |
| 注册 | 「This user ID is already in use.」 | **「A link to activate your account has been emailed to the address provided.」** |

三个容易漏掉的枚举侧信道（OWASP 明确点名）：

1. **时序**：不要 quick-exit。用户不存在时**也要**跑一次同参数的 dummy 哈希验证：

   ```python
   _DUMMY = ph.hash("x" * 32) # 进程启动时算一次
   user = repo.find_by_email(email)
   try:
       ph.verify(user.password_hash if user else _DUMMY, password)
   except VerifyMismatchError:
       raise HTTPException(401, "账号或密码错误")
   ```

2. **HTTP 状态码**：OWASP —— 即使页面文案通用，状态码不同（200 vs 403）依然泄漏。三个入口各自统一（登录一律 401，找回/注册一律 202）
3. **注册已存在邮箱**：不要报「已注册」。改为**给已注册地址发一封「有人尝试用你的邮箱注册，如果是你请直接登录 / 重置密码」的邮件**，接口仍返回同一条通用文案

> ⚠️ 若产品侧坚持要「邮箱已注册」的即时 UX，OWASP 的让步是：对该入口上 CAPTCHA + 严格限流（原文：「Usage of CAPTCHA can be applied to a feature for which a generic error message cannot be returned because the user experience must be preserved」）。**这是明确的取舍，要写进 ADR。**

### 10.4 限流

OWASP：失败计数应**绑定账号而非 IP**（防攻击者切换大量 IP）；推荐**指数退避**而非固定时长；**找回密码流程不得触发账号锁定**（否则可被用来 DoS 已知用户名），且锁定期间应允许通过找回密码流程恢复；CAPTCHA 是纵深防御而非主防，建议失败若干次后才出现。

| 动作 | 维度 | 配额 |
|---|---|---|
| 登录失败 | 账号 | 5 次 / 15 分钟，指数退避（1s→2s→4s…） |
| 登录失败 | 客户端 IP | 30 次 / 15 分钟（挡撞库） |
| 发验证/重置邮件 | 邮箱 | 1 封 / 60 秒，5 封 / 24 小时 |
| 发验证/重置邮件 | IP | 20 封 / 小时 |
| 校验 token | token | 10 次 / 小时（防 token 爆破） |
| 扫码 state 轮询 | state | 1 个 in-flight 请求 |

**与现状对接**：`src/app/login_throttle.py` 的 `LoginThrottle` 已实现滑动窗口 + 键位剪枝，当前 key 是来源 IP。改造两点：
1. key 从 `ip` 改为 `f"acct:{email_lower}"` 与 `f"ip:{addr}"` **双轨并行**，任一命中即拒
2. 其类注释已诚实标注「单容器单进程，进程重启计数清零」—— 多实例部署时换 Redis 后端（`limits>=5.8.0`）

### 10.5 验证过期与状态

- **邮箱验证 token 24 小时**；**密码重置 token 30 分钟**；**扫码 state 5 分钟**（与二维码 `expire_seconds` 对齐）
- `users.email_verified_at IS NULL` 时：允许登录但**不给敏感权限**（导出数据、修改邮箱、调用付费接口），UI 常驻「去验证邮箱」横幅
- OWASP：**「Do not make a change to the account until a valid token is presented」** —— 未验证前不得改动账号状态
- 换邮箱走「双验证」：新地址验证通过后才切换，同时给**旧地址**发变更通知
- 过期数据 GC：`email_verifications` / `oauth_states` / `sessions` 各自的 `expires_at` 索引已建好，挂到现有 APScheduler 上每小时清一次

---

## 11. 实施优先级

| 阶段 | 内容 | 阻塞项 |
|---|---|---|
| **P0** | 五表 DDL + 邮箱注册/登录/验证/重置 + argon2id + 防枚举 + 限流；把现有 `/api/auth/login` 的固定口令迁移为 `users` 表查询 | 无 |
| **P0** | `OAuthProvider` Protocol + registry + `MockScanProvider` + 契约测试骨架 | 无 |
| **P1** | QQ 互联：注册开发者（个人可）→ 创建网站应用 → 立刻拿 appid/appkey → **用开发者本人 QQ 号跑通真链路** | 无（未过审也能测） |
| **P1** | 邮件通道实测：阿里云 DirectMail vs Resend 到达率对比，定通道 | 域名 + DNS |
| **P2** | QQ 应用提交审核（需 ICP 备案，海外站点可免） | ICP 备案 |
| **P2** | QQ UnionID 申请（应用审核状态必须为「通过」） | 上一步 |
| **P3** | 微信：先把 §2.3 的 A/B/C/D 四项核实清楚，再决定走网站应用还是公众号 | 资质结论 |

---

## 12. 参考链接清单（全部已实访）

### 微信开放平台（官方）
1. 网站应用微信登录 — <https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html>
2. 网站应用授权登录（新版同内容） — <https://developers.weixin.qq.com/doc/oplatform/developers/dev/auth/web>
3. 授权后接口调用（UnionID） — <https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Authorized_Interface_Calling_UnionID.html>
4. 微信开放平台介绍 / UnionID 机制 — <https://developers.weixin.qq.com/doc/oplatform/open/intro.html>
5. **注册开放平台（主体类型 + 开发者资质认证 + 未认证限制）** — <https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/operation/open/create.html>
6. 网站应用平台功能介绍（授权回调域 / 业务域名 / PC 小程序插件前置条件） — <https://developers.weixin.qq.com/doc/oplatform/developers/product/webapp/>
7. 配置网站应用业务域名（ICP 备案要求） — <https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_PC_APIs/domain.html>
8. 网站应用调用 PC 微信能力（Chrome 142 local-network-access） — <https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_PC_APIs/guideline.html>
9. 授权登录常见问题（10003 / 10005 排障） — <https://developers.weixin.qq.com/doc/oplatform/developers/troubleshooting/auth.html>
10. 开发者平台概述（与开放平台的关系 / 功能迁移） — <https://developers.weixin.qq.com/doc/oplatform/developers/>

### 微信公众平台 / 服务号（官方）
11. 生成带参数的二维码 — <https://developers.weixin.qq.com/doc/service/api/qrcode/qrcodes/api_createqrcode.html>
12. 接收事件推送（subscribe / SCAN / qrscene_） — <https://developers.weixin.qq.com/doc/service/guide/product/message/Receiving_event_pushes.html>
13. 微信网页授权（适用账号 = 已认证服务号） — <https://developers.weixin.qq.com/doc/service/guide/h5/auth>
14. 服务端 API 总览（/cgi-bin/token、/cgi-bin/stable_token、/cgi-bin/user/info） — <https://developers.weixin.qq.com/doc/service/api/>
15. 《微信公众平台用户信息相关接口调整公告》 — <https://developers.weixin.qq.com/community/develop/doc/00028edbe3c58081e7cc834705b801?blockType=1>

### QQ 互联 / QQ 开放平台（官方）
16. 使用 Authorization_Code 获取 Access_Token — <https://wiki.connect.qq.com/使用Authorization_Code获取Access_Token>
17. 获取用户 OpenID_OAuth2.0 — <https://wiki.connect.qq.com/获取用户openid_oauth2-0>
18. UnionID 介绍（100016 / 100048 / 60 应用上限 / 64 字节预留） — <https://wiki.connect.qq.com/unionid介绍>
19. QQ 互联 UnionID 打通业务自助处理指引 — <https://wiki.connect.qq.com/qq-互联unionid打通业务自助处理指引>
20. get_user_info — <https://wiki.connect.qq.com/get_user_info>
21. 准备工作_OAuth2.0（申请 appid/appkey） — <https://wiki.connect.qq.com/准备工作_oauth2-0>
22. 成为开发者（公司或个人） — <https://wiki.connect.qq.com/成为开发者>
23. **申请相关问题 FAQ（未过审仅开发者账号能登录、海外站免 ICP）** — <https://wiki.connect.qq.com/申请相关问题>
24. 应用审核规范（ICP 备案硬要求、UI 规范、驳回明细） — <https://wiki.connect.qq.com/网站审核规范>
25. 网站应用接入概述 — <https://wiki.connect.qq.com/网站应用接入流程>
26. **QQ 开放平台入驻文档（企业/个体户/个人三类主体材料表）** — <https://q.qq.com/wiki/>
27. QQ 互联管理中心 — <https://connect.qq.com/manage.html>

### 安全标准（官方）
28. OWASP Password Storage Cheat Sheet — <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
29. OWASP Authentication Cheat Sheet — <https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html>
30. OWASP Forgot Password Cheat Sheet — <https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html>
31. RFC 9106 — Argon2 Memory-Hard Function for Password Hashing（§4 Parameter Choice） — <https://www.rfc-editor.org/rfc/rfc9106>
32. NIST SP 800-63B — <https://pages.nist.gov/800-63-4/sp800-63b.html>

### Python 生态
33. argon2-cffi — <https://pypi.org/project/argon2-cffi/> · 参数选择 <https://argon2-cffi.readthedocs.io/en/stable/parameters.html> · profiles 源码 <https://github.com/hynek/argon2-cffi/blob/main/src/argon2/profiles.py>
34. **passlib 维护状态 issue #187** — <https://foss.heptapod.net/python-libs/passlib/-/issues/187>
35. passlib PyPI（1.7.4 / 2020-10-08） — <https://pypi.org/project/passlib/>
36. pwdlib（含 passlib 现状说明） — <https://pypi.org/project/pwdlib/> · <https://github.com/frankie567/pwdlib>
37. PyJWT — <https://pypi.org/project/PyJWT/> · 安全公告 <https://github.com/jpadilla/pyjwt/security/advisories>
38. python-jose — <https://pypi.org/project/python-jose/> · <https://github.com/mpdavis/python-jose>
39. OSV 漏洞库（本报告 CVE 数据源） — <https://osv.dev>
40. aiosmtplib — <https://pypi.org/project/aiosmtplib/>
41. bcrypt — <https://pypi.org/project/bcrypt/>
42. email-validator — <https://pypi.org/project/email-validator/>

### 邮件服务（官方）
43. 阿里云邮件推送 DirectMail 文档首页 — <https://help.aliyun.com/zh/direct-mail/>
44. 设置发信域名（SPF/DKIM/DMARC/MX） — <https://help.aliyun.com/zh/direct-mail/user-guide/how-to-configure-sending-domain-names>
45. SMTP 服务地址与端口 — <https://help.aliyun.com/zh/direct-mail/smtp-endpoints>
46. 腾讯云邮件推送 SES 文档 — <https://cloud.tencent.com/document/product/1288>
47. Resend 文档 — <https://resend.com/docs/introduction>

### 前端
48. MDN EventSource（SSE 6 连接上限） — <https://developer.mozilla.org/en-US/docs/Web/API/EventSource>
