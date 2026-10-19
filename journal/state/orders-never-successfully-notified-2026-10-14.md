# Orders whose 'ready for pickup' notice never reached the customer

Read-only from the live store `operational` on 2026-10-14. **283 orders.**

Every `REPAIR_COMPLETED` notification row in this store is `FAILED` — 300 of 300 — and these 283
orders rest at `READY_FOR_PICKUP` with a failed notice and **no successful message after it**. The
cause is exact and is fixed in `phone-and-tech-full` PR #438: `SMSService.sendSMS` called
`lib/twilio.ts`, a NoOp stub whose every method throws *"Twilio has been removed or is not
configured in this environment"* — that exact string is on 252 of the failed rows. Twilio was
retired at the Dialpad cutover and the sender was never moved.

**This is a FLOOR, not a population count.** Only about **1.3 %** of `communications` rows carry an
`orderId` (the rest carry only a `customerId`), and a customer may also have been telephoned — the
dialer records calls against the customer, not the order. So "no successful message recorded" is
**not** "never told"; it is "no written notice we can prove". A zero here would mean no evidence,
not no problem — and this is not zero.

## Age bands

* over 120 days: **131**
* 60-120 days: **119**
* under 60 days: **33**

The oldest failed notice is **2025-12-25**; the newest is **2026-10-09**. The concentration is explained: the failures begin when Twilio stopped answering.


## The list, oldest failed notice first

| notice failed | days ago | order | opened | customer | phone | device |
|---|---|---|---|---|---|---|
| 2025-12-25 | 293 | WO2512230003 | 2025-12-23 | — | +15742741934 | SAMSUNG A13 Repair |
| 2026-01-20 | 267 | WO2601150004 | 2026-01-15 | Chanoch Saltz | +17323090052 | KYOCERA Cadence Repair |
| 2026-01-21 | 266 | WO2601010004 | 2026-01-01 | Shlessinger | +17325691733 | KYOCERA E4610 Repair |
| 2026-01-21 | 266 | WO2512290002 | 2025-12-29 | Pearl Braun | +19177979939 | CANON SX620HS Repair |
| 2026-01-21 | 266 | WO2512290001 | 2025-12-29 | Pearl Braun | +19177979939 | Apple iPhone 11 Repair |
| 2026-01-21 | 266 | WO2601150001 | 2026-01-15 | Freedman | +18453232607 | CANON SX740HS Repair |
| 2026-01-21 | 266 | WO2512290003 | 2025-12-29 | Chaim Segun | +14243829642 | ASUS L510MA Repair |
| 2026-01-21 | 266 | WO2601010005 | 2026-01-01 | Hershel Schneck | +17182885639 | SAMSUNG S10 Repair |
| 2026-01-21 | 266 | WO2601140004 | 2026-01-14 | Kirzner | +17328501816 | Express: LG Broken Hinge |
| 2026-01-21 | 266 | WO2601150002 | 2026-01-15 | — | +18482104433 | SAMSUNG A14 Repair |
| 2026-01-21 | 266 | WO2601160001 | 2026-01-16 | Zweiback | +18483669120 | LENOVO Laptop Repair |
| 2026-01-21 | 266 | WO2512260001 | 2025-12-26 | Rakowski - Weinberg | +13235590691 | KYOCERA Cadence Repair |
| 2026-01-21 | 266 | WO2512240002 | 2025-12-24 | — | +18482107103 | KYOCERA E4810 Repair |
| 2026-01-21 | 266 | WO2601010003 | 2026-01-01 | Chaim | +13475988428 | KYOCERA Cadence Repair |
| 2026-01-22 | 265 | WO2601220003 | 2026-01-22 | — | +18489863510 | Express: Fig Doesn't Turn On |
| 2026-01-27 | 260 | WO2601270001 | 2026-01-27 | Shloimy Katz | +17329981512 | Kyocera Repair |
| 2026-01-27 | 260 | WO2601270002 | 2026-01-27 | — | +18622718861 | TCL Flip 2 Repair |
| 2026-01-28 | 259 | WO2601220001 | 2026-01-22 | Leiman | +17325750968 | Sonim Repair |
| 2026-01-28 | 259 | WO2601230001 | 2026-01-23 | Stroh | +13475744325 | Unihertz Repair |
| 2026-01-28 | 259 | WO2601220002 | 2026-01-22 | H. Deutsch | +17187816290 | Quinn Repair |
| 2026-02-03 | 253 | WO2602010003 | 2026-02-01 | Chaim Abihsira | +18489860487 | Garmin gps Repair |
| 2026-02-03 | 253 | WO2602010002 | 2026-02-01 | Chaim Abihsira | +18489860487 | Kyocera e4810 Repair |
| 2026-02-05 | 251 | WO2602050001 | 2026-02-05 | Soloman | +17326915277 | Kyocera Cadence Repair |
| 2026-02-05 | 251 | WO2512220003 | 2025-12-22 | Lichtenstein | +17325036608 | QIN F30 Repair |
| 2026-02-06 | 250 | WO2512300001 | 2025-12-30 | Spitz Spitz | +13475815896 | LENOVO Laptop Repair |
| 2026-02-09 | 247 | WO2602030001 | 2026-02-03 | Nuerth | +17327402392 | Lenovo Repair |
| 2026-02-09 | 247 | WO2602090001 | 2026-02-09 | — | +17322795172 | Kyocera E4810 Tier B Repair |
| 2026-02-10 | 246 | WO2512280001 | 2025-12-28 | Reiss | +17325325151 | LG Classic Repair |
| 2026-02-11 | 245 | WO2602110001 | 2026-02-11 | Yehuda Nueman | +18482612761 | Express: KYOCERA Battery Replacement |
| 2026-02-11 | 245 | WO2602010004 | 2026-02-01 | Moshe Chaim Lachman | +14109631497 | GOOGLE Pixel Repair |
| 2026-02-15 | 241 | WO2602130001 | 2026-02-13 | Mordichai Eisenberg | +17325516685 | Veatablet Repair |
| 2026-02-15 | 241 | WO2602120002 | 2026-02-12 | Heimovits | +19089109441 | TCL Flip 2 Repair |
| 2026-02-15 | 241 | WO2602020001 | 2026-02-02 | — | +13472154686 | SAMSUNG A7 Lite 8.7" Repair |
| 2026-02-16 | 240 | WO2602120001 | 2026-02-12 | N. Kovalenko | +17322395882 | LG Exalt Repair |
| 2026-02-16 | 240 | WO2602160001 | 2026-02-16 | Spitzer | +19178482026 | Kyocera E4610 Repair |
| 2026-02-18 | 238 | WO2601010002 | 2026-01-01 | Zelikovitz | +13474004476 | SAMSUNG S23 Repair |
| 2026-02-19 | 237 | WO2602190001 | 2026-02-19 | Zalmin Trabitzsky | +12154365006 | SUNBEAM Repair |
| 2026-02-19 | 237 | WO2601150003 | 2026-01-15 | — | +18482400588 | TOSHIBA Laptop Repair |
| 2026-02-20 | 236 | WO2602180001 | 2026-02-18 | Moshe Levine | +13476759285 | Quinn Repair |
| 2026-03-02 | 226 | WO2602220001 | 2026-02-22 | Mizrachi Mizrachi | +13474540014 | OnePlus Nord N30 5G Repair |
| 2026-03-02 | 226 | WO2602180002 | 2026-02-18 | Yaakov Openhiemer | +19175849424 | ORBIC Flip Phone Repair |
| 2026-03-08 | 220 | WO2602270001 | 2026-02-27 | Yitzchak Brody | +17322780934 | KYOCERA E4610 Repair |
| 2026-03-29 | 199 | WO2602020002 | 2026-02-02 | Ahuva Levovitz | +18483898701 | LG Exalt Repair |
| 2026-05-12 | 155 | WO2605120003 | 2026-05-12 | mrs delman | +17325970877 | Repair - 17325970877 |
| 2026-05-12 | 155 | WO2605120005 | 2026-05-12 | mayer waldman | +18482260108 | Repair - 18482260108 |
| 2026-05-12 | 155 | WO2605120001 | 2026-05-12 | chaim eidelman | +17326041159 | Repair - 17326041159 |
| 2026-05-12 | 155 | WO2605120007 | 2026-05-12 | ms dewick | +17325756877 | Repair - 17325756877 |
| 2026-05-13 | 154 | WO2605120002 | 2026-05-12 | Avrohom Bressler | +17329303026 | Screen Glitch Repair — Bressler (Shapiro Referral) |
| 2026-05-13 | 154 | WO2605120006 | 2026-05-12 | mrs frischman | +13474088027 | Repair - 13474088027 |
| 2026-05-13 | 154 | WO2605130002 | 2026-05-13 | — | +13478863969 | SD Card Repair — Stolper (Shapiro Referral) |
| 2026-05-14 | 153 | WO2605130005 | 2026-05-13 | — | +17323306591 | Shell Swap — Cohen (Shapiro Referral) |
| 2026-05-14 | 153 | WO2605140002 | 2026-05-14 | yehuda stern | +18452741922 | Repair - 18452741922 |
| 2026-05-14 | 153 | WO2605130001 | 2026-05-13 | Rabbi Bausman | +18482999824 | Screen Replacement — Bausman (Shapiro Referral) |
| 2026-05-14 | 153 | WO2605140001 | 2026-05-14 | chaya drillman | +17322283644 | Repair - 17322283644 |
| 2026-05-15 | 152 | WO2605130003 | 2026-05-13 | mazal semah | +18483664023 | Repair - 18483664023 |
| 2026-05-19 | 148 | WO2605190003 | 2026-05-19 | aliza wolf | +18623184278 | Repair - 18623184278 |
| 2026-05-19 | 148 | WO2605190004 | 2026-05-19 | bamberger man | +17326146974 | Repair - 17326146974 |
| 2026-05-19 | 148 | WO2605190005 | 2026-05-19 | Mrs Rudnicki | +18482408877 | Kyocera E4610 Hinge + Bottom Mic — Rudnicki (Shapiro Referra |
| 2026-05-19 | 148 | WO2605190006 | 2026-05-19 | sari samet | +19087830096 | Repair - 19087830096 |
| 2026-05-19 | 148 | WO2605190007 | 2026-05-19 | ezra faham | +18482264727 | Repair - 18482264727 |
| 2026-05-19 | 148 | WO2605190008 | 2026-05-19 | mrs landesman | +17325516923 | Repair - 17325516923 |
| 2026-05-19 | 148 | WO2605190010 | 2026-05-19 | Ms Katz | +17325033591 | Kyocera E4610 Cable Repair — Katz (Shapiro Referral) |
| 2026-05-20 | 147 | WO2605190014 | 2026-05-19 | malki blier | +17329486030 | Repair - 17329486030 |
| 2026-05-20 | 147 | WO2605200001 | 2026-05-20 | mendy gould | +16179479517 | Repair - 16179479517 |
| 2026-05-20 | 147 | WO2605200002 | 2026-05-20 | bamberger man | +17326146974 | Repair - 17326146974 |
| 2026-05-20 | 147 | WO2605200003 | 2026-05-20 | shimon greenfeld | +19086927704 | Repair - 19086927704 |
| 2026-05-20 | 147 | WO2605200004 | 2026-05-20 | zanvil katz | +12163701700 | Repair - 12163701700 |
| 2026-05-20 | 147 | WO2605200005 | 2026-05-20 | esti garfunkel | +18482102786 | Repair - 18482102786 |
| 2026-05-20 | 147 | WO2605200006 | 2026-05-20 | yaakov rosenbaum | +18483308037 | Repair - 18483308037 |
| 2026-05-20 | 147 | WO2605130004 | 2026-05-13 | — | +17329949678 | Hinge Repair — Klein (Shapiro Referral) |
| 2026-05-25 | 142 | WO2605250001 | 2026-05-25 | perel pluthok | +13472776025 | Repair - 13472776025 |
| 2026-05-25 | 142 | WO2605250002 | 2026-05-25 | kalman rosenberg | +17322163402 | Repair - 17322163402 |
| 2026-05-25 | 142 | WO2605250003 | 2026-05-25 | mrs snyder | +17326856931 | Repair - 17326856931 |
| 2026-05-25 | 142 | WO2605250004 | 2026-05-25 | shmuel zafrani | +18482407528 | Repair - 18482407528 |
| 2026-05-25 | 142 | WO2605250005 | 2026-05-25 | rabbi taub | +18482993426 | Repair - 18482993426 |
| 2026-05-25 | 142 | WO2605200007 | 2026-05-20 | zech weisenfeld | +18456593820 | Repair - 18456593820 |
| 2026-05-26 | 141 | WO2605260001 | 2026-05-26 | mrs smith | +17328144881 | Repair - 17328144881 |
| 2026-05-26 | 141 | WO2605250008 | 2026-05-25 | ms burstyn | +17325814537 | Repair - 17325814537 |
| 2026-05-27 | 140 | WO2605270002 | 2026-05-27 | zalman frankel | +18456645757 | Repair - 18456645757 |
| 2026-05-27 | 140 | WO2605270001 | 2026-05-27 | sadi shlomo | +13472594433 | Repair - 13472594433 |
| 2026-05-27 | 140 | WO2605270003 | 2026-05-27 | ms leizerson | +17322374070 | Repair - 17322374070 |
| 2026-05-27 | 140 | WO2605270004 | 2026-05-27 | leah feder | +17327408493 | Repair - 17327408493 |
| 2026-05-27 | 140 | WO2605270005 | 2026-05-27 | — | +17326778482 | Repair - 17326778482 |
| 2026-05-27 | 140 | WO2605190011 | 2026-05-19 | — | +17326778482 | Repair - 17326778482 |
| 2026-05-27 | 140 | WO2605270006 | 2026-05-27 | fraydie cohen | +17329985626 | Repair - 17329985626 |
| 2026-05-28 | 139 | WO2605260003 | 2026-05-26 | mrs licht | +13473091979 | Repair - 13473091979 |
| 2026-05-28 | 139 | WO2605280005 | 2026-05-28 | mrs gold | +15162324434 | Repair - 15162324434 |
| 2026-05-28 | 139 | WO2605280006 | 2026-05-28 | shlomo kessler | +18482380234 | Repair - 18482380234 |
| 2026-05-28 | 139 | WO2605280002 | 2026-05-28 | mrs beeber | +13474249722 | Repair - 13474249722 |
| 2026-05-28 | 139 | WO2605280008 | 2026-05-28 | rabbi from baltimore | +14104587630 | Repair - 14104587630 |
| 2026-05-29 | 138 | WO2605280004 | 2026-05-28 | rabbi bechhofer | +17325341153 | Repair - 17325341153 |
| 2026-05-29 | 138 | WO2605290001 | 2026-05-29 | mr mandelbaum | +18482408832 | Repair - 18482408832 |
| 2026-05-29 | 138 | WO2605290002 | 2026-05-29 | avishai blacksman | +18482260153 | Repair - 18482260153 |
| 2026-05-29 | 138 | WO2605190013 | 2026-05-19 | Chaya Barrish | +17325694180 | iPhone 11 Screen Repair — Barrish (Shapiro Referral) |
| 2026-05-29 | 138 | WO2605290004 | 2026-05-29 | mendy gould | +16179479517 | Repair - 16179479517 |
| 2026-06-01 | 135 | WO2605290005 | 2026-05-29 | noach hess | +17322326678 | Repair - 17322326678 |
| 2026-06-01 | 135 | WO2606010001 | 2026-06-01 | mrs zoldin | +13474013277 | Repair - 13474013277 |
| 2026-06-02 | 134 | WO2606020002 | 2026-06-02 | mrs rosenberg | +17326042830 | Repair - 17326042830 |
| 2026-06-02 | 134 | WO2606010005 | 2026-06-01 | mrs pom phone | +13475173434 | Repair - 13475173434 |
| 2026-06-02 | 134 | WO2606020001 | 2026-06-02 | moshe lichter | +18482260964 | Repair - 18482260964 |
| 2026-06-02 | 134 | WO2606020004 | 2026-06-02 | meir rokowsky | +12014146597 | Repair - 12014146597 |
| 2026-06-02 | 134 | WO2606020005 | 2026-06-02 | pessy bohensky | +18482103383 | Repair - 18482103383 |
| 2026-06-03 | 133 | WO2605290003 | 2026-05-29 | mrs shternbuch | +17183606061 | Repair - 17183606061 |
| 2026-06-03 | 133 | WO2606030001 | 2026-06-03 | chaim ozer wolf | +13473067073 | Repair - 13473067073 |
| 2026-06-03 | 133 | WO2606020006 | 2026-06-02 | mr weitz | +19085490358 | OnePlus Nord N30 5G Screen Repair |
| 2026-06-03 | 133 | WO2606020007 | 2026-06-02 | mrs gartenhaus | +17326083687 | Repair - 17326083687 |
| 2026-06-04 | 132 | WO2605280007 | 2026-05-28 | sruly taub | +17322883640 | Repair - 17322883640 |
| 2026-06-05 | 131 | WO2606040002 | 2026-06-04 | moshe shakshuka | +18482996264 | Repair - 18482996264 |
| 2026-06-05 | 131 | WO2606040001 | 2026-06-04 | mrs rubin | +13472543031 | Repair - 13472543031 |
| 2026-06-05 | 131 | WO2606050001 | 2026-06-05 | mr gawartin | +18455530800 | Repair - 18455530800 |
| 2026-06-05 | 131 | WO2606050002 | 2026-06-05 | sarah levi | +17325571217 | Repair - 17325571217 |
| 2026-06-08 | 128 | WO2606080001 | 2026-06-08 | mrs rosenberg | +18485258790 | Repair - 18485258790 |
| 2026-06-08 | 128 | WO2606080006 | 2026-06-08 | dovid weinreb | +17573359040 | Repair - 17573359040 |
| 2026-06-08 | 128 | WO2606080004 | 2026-06-08 | mrs rubin baltimore | +18455874059 | Repair - 18455874059 |
| 2026-06-10 | 126 | WO2606100001 | 2026-06-10 | ms blumenthol | +17328644790 | Repair - 17328644790 |
| 2026-06-10 | 126 | WO2605280003 | 2026-05-28 | moshe nahem | +19086753233 | Repair - 19086753233 |
| 2026-06-10 | 126 | WO2606100002 | 2026-06-10 | meir plotnick | +17322523650 | Repair - 17322523650 |
| 2026-06-10 | 126 | WO2606100006 | 2026-06-10 | rabbi nussbaum | +17323093128 | Repair - 17323093128 |
| 2026-06-11 | 125 | WO2606100005 | 2026-06-10 | rabbi shuster | +18482101157 | Repair - 18482101157 |
| 2026-06-11 | 125 | WO2606110001 | 2026-06-11 | mrs brisman | +19178801521 | Repair - 19178801521 |
| 2026-06-11 | 125 | WO2606100004 | 2026-06-10 | rabbi nierenberg | +17326684740 | Repair - 17326684740 |
| 2026-06-11 | 125 | WO2606110002 | 2026-06-11 | hindy bornstein | +17327323709 | Repair - 17327323709 |
| 2026-06-11 | 125 | WO2606110003 | 2026-06-11 | tzvi miller | +17326081354 | Repair - 17326081354 |
| 2026-06-11 | 125 | WO2605250006 | 2026-05-25 | dovid lax | +14104093662 | Repair - 14104093662 |
| 2026-06-12 | 124 | WO2606120002 | 2026-06-12 | yehuda beiberfeld | +16107313887 | Repair - 16107313887 |
| 2026-06-12 | 124 | WO2606120001 | 2026-06-12 | mrs eichorn | +18453766892 | Repair - 18453766892 |
| 2026-06-15 | 121 | WO2606080010 | 2026-06-08 | ms perlow | +18483894351 | Repair - 18483894351 |
| 2026-06-15 | 121 | WO2606150002 | 2026-06-15 | eli schriber | +18485251896 | Repair - 18485251896 |
| 2026-06-15 | 121 | WO2606090005 | 2026-06-09 | Witkin Witkin | +17329662658 | Repair - 17329662658 |
| 2026-06-15 | 121 | WO2606150003 | 2026-06-15 | eli gurwitz | +13476774857 | Repair - 13476774857 |
| 2026-06-15 | 121 | WO2606150005 | 2026-06-15 | mrs raitzik | +14102998611 | Repair - 14102998611 |
| 2026-06-16 | 120 | WO2606150001 | 2026-06-15 | mordechai nahem | +17324561260 | Repair - 17324561260 |
| 2026-06-16 | 120 | WO2606160002 | 2026-06-16 | avi neugroschl | +18457467745 | Repair - 18457467745 |
| 2026-06-16 | 120 | WO2606160004 | 2026-06-16 | mrs waxman | +17325817769 | Repair - 17325817769 |
| 2026-06-17 | 119 | WO2606080005 | 2026-06-08 | yakov pendrak | +16109456307 | Repair - 16109456307 |
| 2026-06-17 | 119 | WO2605250007 | 2026-05-25 | shloimy nebenzahl | +17325690935 | Repair - 17325690935 |
| 2026-06-17 | 119 | WO2606090001 | 2026-06-09 | chaim senderovitz | +13479025151 | Repair - 13479025151 |
| 2026-06-17 | 119 | WO2606170001 | 2026-06-17 | rabbi salamon | +18482245747 | Repair - 18482245747 |
| 2026-06-18 | 118 | WO2606180001 | 2026-06-18 | blank pearl | +17322671331 | Repair - 17322671331 |
| 2026-06-18 | 118 | WO2606180002 | 2026-06-18 | yocheved kaplan | +19295543043 | Repair - 19295543043 |
| 2026-06-18 | 118 | WO2606180003 | 2026-06-18 | blank pohrille | +18482857198 | Repair - 18482857198 |
| 2026-06-18 | 118 | WO2606180004 | 2026-06-18 | rena gross | +14436132346 | Repair - 14436132346 |
| 2026-06-18 | 118 | WO2606090004 | 2026-06-09 | mrs kaufman | +19089100921 | Repair - 19089100921 |
| 2026-06-18 | 118 | WO2606180006 | 2026-06-18 | mrs whiteman | +18483336341 | Repair - 18483336341 |
| 2026-06-18 | 118 | WO2606180007 | 2026-06-18 | mr bornstein | +19089103306 | Repair - 19089103306 |
| 2026-06-22 | 114 | WO2606190001 | 2026-06-19 | shalom tansky | +17329484030 | Repair - 17329484030 |
| 2026-06-22 | 114 | WO2606220001 | 2026-06-22 | avrohom raber | +18482245346 | Repair - 18482245346 |
| 2026-06-22 | 114 | WO2606220004 | 2026-06-22 | mrs shwartz | +13473933220 | Repair - 13473933220 |
| 2026-06-22 | 114 | WO2606010002 | 2026-06-01 | yakov dov kaplan | +17322280912 | Repair - 17322280912 |
| 2026-06-22 | 114 | WO2606150004 | 2026-06-15 | mrs klein | +17326641343 | Repair - 17326641343 |
| 2026-06-22 | 114 | WO2606220006 | 2026-06-22 | ms shustal | +18489863959 | Repair - 18489863959 |
| 2026-06-22 | 114 | WO2606220005 | 2026-06-22 | — | +17325036369 | Repair - 17325036369 |
| 2026-06-23 | 113 | WO2606230001 | 2026-06-23 | mr nierenberg | +13478312008 | Repair - 13478312008 |
| 2026-06-23 | 113 | WO2606230002 | 2026-06-23 | mr kanarek | +18482018095 | Repair - 18482018095 |
| 2026-06-23 | 113 | WO2606230004 | 2026-06-23 | mrs atlas | +18482996734 | Repair - 18482996734 |
| 2026-06-24 | 112 | WO2606240003 | 2026-06-24 | yisroel reifman | +18483738293 | Repair - 18483738293 |
| 2026-06-25 | 111 | WO2606250001 | 2026-06-25 | mr gombo | +17187448136 | Repair - 17187448136 |
| 2026-06-25 | 111 | WO2606250002 | 2026-06-25 | mrs blank | +18485250019 | Repair - 18485250019 |
| 2026-06-26 | 110 | WO2606260001 | 2026-06-26 | blank lobestein | +17329985049 | Repair - 17329985049 |
| 2026-06-26 | 110 | WO2606240004 | 2026-06-24 | sruly rubin | +19172027679 | Repair - 19172027679 |
| 2026-06-29 | 107 | WO2606290001 | 2026-06-29 | yossi singer | +13479846565 | Repair - 13479846565 |
| 2026-06-29 | 107 | WO2606290002 | 2026-06-29 | shlomo kaye | +17327595906 | Repair - 17327595906 |
| 2026-06-30 | 106 | WO2606290005 | 2026-06-29 | zevi eisenberger | +19083420231 | Repair - 19083420231 |
| 2026-06-30 | 106 | WO2606300001 | 2026-06-30 | mrs kuritzky | +17326379325 | Repair - 17326379325 |
| 2026-06-30 | 106 | WO2606300002 | 2026-06-30 | mr ullman | +18482453390 | Repair - 18482453390 |
| 2026-06-30 | 106 | WO2606300003 | 2026-06-30 | mrs goldberg | +17322280308 | Repair - 17322280308 |
| 2026-06-30 | 106 | WO2606220002 | 2026-06-22 | mrs neumann | +19087839851 | Repair - 19087839851 |
| 2026-06-30 | 106 | WO2606300005 | 2026-06-30 | yehuda oppenheim | +19803551308 | Repair - 19803551308 |
| 2026-07-01 | 105 | WO2607010001 | 2026-07-01 | shmuly kahan | +19292021009 | Repair - 19292021009 |
| 2026-07-01 | 105 | WO2606300004 | 2026-06-30 | rabbi bodner | +18455581290 | Repair - 18455581290 |
| 2026-07-02 | 104 | WO2607020001 | 2026-07-02 | blank malinowitz | +17325815207 | Repair - 17325815207 |
| 2026-07-02 | 104 | WO2607020002 | 2026-07-02 | mrs greenwood | +18455020780 | Repair - 18455020780 |
| 2026-07-03 | 103 | WO2607030001 | 2026-07-03 | tzvi hirsch | +18485255381 | Repair - 18485255381 |
| 2026-07-03 | 103 | WO2607020005 | 2026-07-02 | mrs hersh | +17325527346 | Repair - 17325527346 |
| 2026-07-06 | 100 | WO2607060001 | 2026-07-06 | mrs weinberg | +19176539161 | Repair - 19176539161 |
| 2026-07-06 | 100 | WO2607010002 | 2026-07-01 | chananya freidman | +18489866466 | Repair - 18489866466 |
| 2026-07-06 | 100 | WO2607060002 | 2026-07-06 | mr kirzner | +18482242691 | Repair - 18482242691 |
| 2026-07-06 | 100 | WO2607060004 | 2026-07-06 | tzvi herzka | +18482384439 | Repair - 18482384439 |
| 2026-07-06 | 100 | WO2607020003 | 2026-07-02 | moshe rosen | +18454222860 | Repair - 18454222860 |
| 2026-07-06 | 100 | WO2607060003 | 2026-07-06 | shalom tansky | +17329484030 | Repair - 17329484030 |
| 2026-07-06 | 100 | WO2607020004 | 2026-07-02 | asher beno | +18482408579 | Repair - 18482408579 |
| 2026-07-06 | 100 | WO2607060008 | 2026-07-06 | yehuda israelian | +19296661854 | Repair - 19296661854 |
| 2026-07-06 | 100 | WO2607060007 | 2026-07-06 | mrs lipschetz | +18482878814 | Repair - 18482878814 |
| 2026-07-07 | 99 | WO2607060009 | 2026-07-06 | mrs frankel | +17862758461 | Repair - 17862758461 |
| 2026-07-07 | 99 | WO2607070001 | 2026-07-07 | rabbi dellman | +19089103448 | Repair - 19089103448 |
| 2026-07-07 | 99 | WO2607060006 | 2026-07-06 | ezra max | +13478533790 | Repair - 13478533790 |
| 2026-07-07 | 99 | WO2606090002 | 2026-06-09 | rabbi shochet | +18482453600 | Repair - 18482453600 |
| 2026-07-07 | 99 | WO2607070002 | 2026-07-07 | miss plotnick | +19179367756 | Repair - 19179367756 |
| 2026-07-07 | 99 | WO2606110004 | 2026-06-11 | rivky shwartzman | +17329420889 | Repair - 17329420889 |
| 2026-07-07 | 99 | WO2607070003 | 2026-07-07 | miss rottenberg | +17325697229 | Repair - 17325697229 |
| 2026-07-08 | 98 | WO2606080003 | 2026-06-08 | david girls | +17328333965 | Repair - 17328333965 |
| 2026-07-08 | 98 | WO2607080003 | 2026-07-08 | rabbi reinman | +17322787200 | Repair - 17322787200 |
| 2026-07-08 | 98 | WO2607080004 | 2026-07-08 | gavi rubenfeld | +17325692764 | Repair - 17325692764 |
| 2026-07-08 | 98 | WO2607080005 | 2026-07-08 | moshe brown | +12163151752 | Repair - 12163151752 |
| 2026-07-09 | 97 | WO2607080001 | 2026-07-08 | chaim orlansky | +17325523669 | Repair - 17325523669 |
| 2026-07-09 | 97 | WO2607090001 | 2026-07-09 | avrohom nueman | +18483260809 | Repair - 18483260809 |
| 2026-07-09 | 97 | WO2607090002 | 2026-07-09 | michal cohen | +17189547115 | Repair - 17189547115 |
| 2026-07-09 | 97 | WO2607090003 | 2026-07-09 | random sale | +19088395618 | Repair - 19088395618 |
| 2026-07-09 | 97 | WO2607090004 | 2026-07-09 | dasniel kranz | +17325341640 | Repair - 17325341640 |
| 2026-07-09 | 97 | WO2606290006 | 2026-06-29 | henchy klein | +13474432216 | Repair - 13474432216 |
| 2026-07-09 | 97 | WO2607090007 | 2026-07-09 | yecheil reiner | +19175381079 | Repair - 19175381079 |
| 2026-07-09 | 97 | WO2607090005 | 2026-07-09 | rabbi lansky | +12165369682 | Repair - 12165369682 |
| 2026-07-10 | 96 | WO2607090008 | 2026-07-09 | rabbi meisles | +17326746333 | Repair - 17326746333 |
| 2026-07-13 | 93 | WO2607130001 | 2026-07-13 | yisroel shwadron | +17324927932 | Repair - 17324927932 |
| 2026-07-13 | 93 | WO2607090006 | 2026-07-09 | yakov kilberg | +17326748951 | Repair - 17326748951 |
| 2026-07-13 | 93 | WO2607130002 | 2026-07-13 | avrumi shapiro | +18483735799 | Repair - 18483735799 |
| 2026-07-13 | 93 | WO2607130003 | 2026-07-13 | nashi nueman | +18482991890 | Repair - 18482991890 |
| 2026-07-14 | 92 | WO2607140001 | 2026-07-14 | menachem pollack | +18483269094 | Repair - 18483269094 |
| 2026-07-14 | 92 | WO2607140003 | 2026-07-14 | rabbi gluestein | +17325033232 | Repair - 17325033232 |
| 2026-07-14 | 92 | WO2607140004 | 2026-07-14 | mrs rackoff | +18483469688 | Repair - 18483469688 |
| 2026-07-15 | 91 | WO2607150003 | 2026-07-15 | yanky kroll | +12489311142 | Repair - 12489311142 |
| 2026-07-16 | 90 | WO2607160002 | 2026-07-16 | rabbi hess | +17325474501 | Repair - 17325474501 |
| 2026-07-16 | 90 | WO2607150004 | 2026-07-15 | mrs kanarek | +17322324974 | Repair - 17322324974 |
| 2026-07-17 | 89 | WO2607160003 | 2026-07-16 | avrohom nueman | +18483260809 | Repair - 18483260809 |
| 2026-07-17 | 89 | WO2607170003 | 2026-07-17 | yisroel perlow | +19174439515 | Repair - 19174439515 |
| 2026-07-20 | 86 | WO2607200005 | 2026-07-20 | eli tennehause | +12015093136 | Repair - 12015093136 |
| 2026-07-20 | 86 | WO2607200004 | 2026-07-20 | mrs lipshitz | +17325435366 | Repair - 17325435366 |
| 2026-07-20 | 86 | WO2607200003 | 2026-07-20 | rabbi freidman | +13478311234 | Repair - 13478311234 |
| 2026-07-20 | 86 | WO2607200009 | 2026-07-20 | ms kokis | +17329611548 | Repair - 17329611548 |
| 2026-07-20 | 86 | WO2607160001 | 2026-07-16 | gitel berkovitz | +13475247128 | Repair - 13475247128 |
| 2026-07-20 | 86 | WO2607170002 | 2026-07-17 | rabbi lax | +19175333993 | Repair - 19175333993 |
| 2026-07-20 | 86 | WO2607200011 | 2026-07-20 | dovid tovi | +18452745051 | Repair - 18452745051 |
| 2026-07-21 | 85 | WO2607210002 | 2026-07-21 | mr shlezinger | +18482457112 | Repair - 18482457112 |
| 2026-07-21 | 85 | WO2607210003 | 2026-07-21 | ms bruchi | +17326915125 | Repair - 17326915125 |
| 2026-07-21 | 85 | WO2607200002 | 2026-07-20 | rabbi rosenberg | +19087839033 | Repair - 19087839033 |
| 2026-07-21 | 85 | WO2607210004 | 2026-07-21 | aaron rosenthal | +19087833415 | Repair - 19087833415 |
| 2026-07-21 | 85 | WO2607210007 | 2026-07-21 | dovid zilber | +12169240724 | Repair - 12169240724 |
| 2026-07-21 | 85 | WO2607210006 | 2026-07-21 | david machon | +17329241526 | Repair - 17329241526 |
| 2026-07-22 | 84 | WO2607210005 | 2026-07-21 | nusi rubin | +19173273121 | Repair - 19173273121 |
| 2026-07-22 | 84 | WO2607200006 | 2026-07-20 | zlatik husband | +19177420514 | Repair - 19177420514 |
| 2026-07-24 | 82 | WO2607200010 | 2026-07-20 | galaxy snine | +17188728866 | Repair - 17188728866 |
| 2026-07-27 | 79 | WO2607240004 | 2026-07-24 | yitzy weber | +16463212689 | Repair - 16463212689 |
| 2026-07-27 | 79 | WO2607240001 | 2026-07-24 | hindy reisz | +18483734678 | Repair - 18483734678 |
| 2026-07-27 | 79 | WO2607240003 | 2026-07-24 | mrs kitevitz | +17328147049 | Repair - 17328147049 |
| 2026-07-27 | 79 | WO2607150002 | 2026-07-15 | yael hershkowitz | +17328824238 | Repair - 17328824238 |
| 2026-07-27 | 79 | WO2607270002 | 2026-07-27 | mrs nueman wd | +17322885454 | Repair - 17322885454 |
| 2026-07-27 | 79 | WO2607270004 | 2026-07-27 | mrs karmel | +17326065377 | Repair - 17326065377 |
| 2026-07-27 | 79 | WO2607270005 | 2026-07-27 | berenath brother | +17325037060 | Repair - 17325037060 |
| 2026-07-29 | 77 | WO2607290001 | 2026-07-29 | mrs rabinowitz | +18628232811 | Repair - 18628232811 |
| 2026-07-29 | 77 | WO2607290003 | 2026-07-29 | rabbi dowek | +18482239150 | Repair - 18482239150 |
| 2026-07-30 | 76 | WO26072412512 | 2026-07-24 | Werner | 7328044539 | HP Laptop 250 G10 — Charging port cable replacement |
| 2026-07-30 | 76 | WO2607300001 | 2026-07-30 | mrs gewirtz | +17327797253 | Repair - 17327797253 |
| 2026-07-31 | 75 | WO26072412522 | 2026-07-24 | Chaim Margulies | +13474185638 | Lenovo IdeaPad 1 15IJL7 (82LX) - screen not displaying (not |
| 2026-07-31 | 75 | WO26072412515 | 2026-07-24 | Chaim Margulies | +13474185638 | Lenovo IdeaPad 1 15IJL7 (82LX) — Screen not displaying (not |
| 2026-08-04 | 71 | WO2608040004 | 2026-08-04 | mrs meyers | +19176278712 | Repair - 19176278712 |
| 2026-08-04 | 71 | WO2608040005 | 2026-08-04 | rabbi hauer | +18482403889 | Repair - 18482403889 |
| 2026-08-04 | 71 | WO2608040008 | 2026-08-04 | ari rumpler | +13474157832 | Repair - 13474157832 |
| 2026-08-04 | 71 | WO2608040006 | 2026-08-04 | rabbi lichman | +18485257267 | Repair - 18485257267 |
| 2026-08-04 | 71 | WO2607300002 | 2026-07-30 | gitty werner | +17322322117 | Repair - 17322322117 |
| 2026-08-04 | 71 | WO2608040009 | 2026-08-04 | mrs dickstein | +17325971887 | Repair - 17325971887 |
| 2026-09-01 | 43 | WO26082712645 | 2026-08-27 | Abramczyk | +18482857640 | 64GB (57.9 GiB) microSD/SD card not reading - logical FAT co |
| 2026-09-01 | 43 | WO2609010002 | 2026-09-01 | mrs gestetner | +18453237194 | Repair - 18453237194 |
| 2026-09-01 | 43 | WO2608190004 | 2026-08-19 | shamshon miller | +17322888750 | Repair - 17322888750 |
| 2026-09-01 | 43 | WO26082712651 | 2026-08-27 | Felder | +17327492958 | Seagate BUP Slim 2TB external USB hard drive — not mounting, |
| 2026-09-01 | 43 | WO26082712639 | 2026-08-27 | Mrs Deustch | +17325694097 | Samsung Galaxy S10e (Smart Switch backup) — Customer needs S |
| 2026-09-01 | 43 | WO26082712664 | 2026-08-27 | Heisler | 7328537519 | iPhone 14 Pro (Lightning confirmed, Dynamic Island, 3 rear c |
| 2026-09-01 | 43 | WO26082712666 | 2026-08-27 | Kesserman | +17326930054 | Kyocera E4610 (Verizon) data recovery. Blown fuse caused dea |
| 2026-09-01 | 43 | WO26082712670 | 2026-08-27 | Shira Schuck | 9738004772 | laptop |
| 2026-09-01 | 43 | WO26082712677 | 2026-08-27 | Kleimar | +18482243248 | Motorola Moto G Play 2024 screen replacement case for Kleima |
| 2026-09-01 | 43 | WO26082712685 | 2026-08-27 | Michael West | +19086751739 | Samsung Galaxy S20+ 5G (SM-G986U, 128GB, Cosmic Gray) - purp |
| 2026-09-01 | 43 | WO26082712686 | 2026-08-27 | Yoel Charach | 8482991455 | Sandisk USB Drive (Clip Trace) |
| 2026-09-01 | 43 | WO26082712689 | 2026-08-27 | Felder | +17327492958 | Repair for Felder |
| 2026-09-01 | 43 | WO26082712694 | 2026-08-27 | Kreisman | 3478315540 | Repair for Kreisman |
| 2026-09-01 | 43 | WO26082712693 | 2026-08-27 | Laskin | +18482407678 | Samsung Galaxy Z Flip3 5G (SM-F711U) — inner foldable screen |
| 2026-09-01 | 43 | WO26082712684 | 2026-08-27 | Shimon Weiss | +17323304906 | Samsung Galaxy A02s (SM-A025V) cracked-screen intake. Custom |
| 2026-09-01 | 43 | WO26081112580 | 2026-08-11 | Yehudis Levovitz | 9089104065 | Lenovo IdeaPad 3 15ITL6 — Coffee spill, won't charge (chargi |
| 2026-09-01 | 43 | WO26082712678 | 2026-08-27 | Binyamin Kaufman | +18455876240 | Water-damaged Google Pixel 7 (GVU6C), IMEI 351610586161409, |
| 2026-09-01 | 43 | WO2609010005 | 2026-09-01 | daniel weiskof | +12013157494 | Repair - 12013157494 |
| 2026-09-01 | 43 | WO2609010007 | 2026-09-01 | yosef horowitz | +19738421085 | Repair - 19738421085 |
| 2026-09-01 | 43 | WO2609010009 | 2026-09-01 | levovitz cousin | +12015438646 | Repair - 12015438646 |
| 2026-09-02 | 42 | WO2609020001 | 2026-09-02 | issi duetsch | +19087835716 | Repair - 19087835716 |
| 2026-09-02 | 42 | WO2609020004 | 2026-09-02 | sophia leniado | +17324437065 | Repair - 17324437065 |
| 2026-09-03 | 41 | WO2609030002 | 2026-09-03 | mordechai rosen | +16467152970 | Repair - 16467152970 |
| 2026-09-03 | 41 | WO2609030005 | 2026-09-03 | mrs whiteman | +18483336341 | Repair - 18483336341 |
| 2026-09-04 | 40 | WO2609040001 | 2026-09-04 | Yehuda Pinter | 8484808424 | Repair - 18484808424 |
| 2026-09-07 | 37 | WO2609070003 | 2026-09-07 | mrs carr | +12039880145 | Repair - 12039880145 |
| 2026-09-07 | 37 | WO2609020002 | 2026-09-02 | mrs meyer | +18482245174 | Repair - 18482245174 |
| 2026-09-07 | 37 | WO2609070001 | 2026-09-07 | rabbi greenfeld | +18456590807 | Repair - 18456590807 |
| 2026-09-07 | 37 | WO2609070004 | 2026-09-07 | yehuda rozansky | +19176351660 | Repair - 19176351660 |
| 2026-09-08 | 36 | WO2608140001 | 2026-08-14 | ms godfrey | +19297220836 | Repair - 19297220836 |
| 2026-09-08 | 36 | WO2609030003 | 2026-09-03 | mr david | +18483291566 | Repair - 18483291566 |
| 2026-09-08 | 36 | WO2609030001 | 2026-09-03 | sarah levi | +17325571217 | Repair - 17325571217 |
| 2026-10-09 | 5 | WO2610090001 | 2026-10-09 | UX Test Yosef Berg | +17325550147 | iPhone 13, black |

## What this list is FOR

Deciding whether to re-notify. Nothing has been sent and nothing will be without the owner's
explicit approval of the exact message text — re-notifying 283 customers is outbound
communication, and the sender fix (PR #438) is not deployed.

