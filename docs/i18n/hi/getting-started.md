<!-- यह docs/getting-started.md (स्रोत कमिट: 00d6097) का समुदाय-अनुरक्षित अनुवाद है — अंग्रेज़ी संस्करण ही आधिकारिक है। -->

# शुरुआत करें

## इंस्टॉल

टर्मिनल से इंस्टॉल करने का सबसे सुरक्षित तरीका है कि रिमोट बूटस्ट्रैप स्क्रिप्ट चलाने के बजाय pipx से प्रकाशित पैकेज इंस्टॉल किया जाए:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

अगर आपको बिना किसी पूर्व-आवश्यकता वाला डेस्कटॉप बूटस्ट्रैप चाहिए, तो किसी भरोसेमंद कमिट या रिलीज़ से `deploy/desktop/install.sh` या `deploy/desktop/install.ps1` डाउनलोड करें, उसे सत्यापित करें, और `MAVERICK_REF` में पूरा 40-अक्षर वाला कमिट SHA सेट करें। ये स्क्रिप्ट डिफ़ॉल्ट रूप से परिवर्तनशील ब्रांच/टैग रेफ़रेंस अस्वीकार कर देती हैं।

PyPI पैकेज `maverick-agent` है (`maverick` नाम पहले से किसी और ने ले रखा है)। `[installer]` एक्स्ट्रा विज़ार्ड को कर्नेल वाले उसी pipx एनवायरनमेंट में इंस्टॉल करता है, ताकि `maverick init` कमांड उपलब्ध रहे।

डेवलपमेंट के दौरान सोर्स से:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## पहली बार चलाना

```bash
maverick init
```

विज़ार्ड में लगभग 2 मिनट लगते हैं। यह `~/.maverick/config.toml` और `~/.maverick/.env` लिखता है।

इसके बाद:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## स्वार्म को लक्ष्य विभाजित करते हुए देखें

दूसरे टर्मिनल में `maverick monitor` चलाएँ। ऑर्केस्ट्रेटर लक्ष्य की योजना बनाता है, फिर समानांतर काम करने वाले विशेषज्ञ सब-एजेंट शुरू करता है — यहाँ एक रिसर्चर API का पता लगाता है, एक कोडर टूल लिखता है, और एक वेरिफ़ायर उसे चलाकर जाँचता है:

```
Goal #1 active  2m elapsed
Build a CLI that emails me a digest of today's top Hacker News stories

Plan tree
  ├─        done  #2 Research the Hacker News Firebase API
  ├─      active  #3 Write the digest CLI (fetch + format + send)
  ├─      active  #4 Verify it runs and emails a sample digest
  ├─     pending  #5 Write a short usage README

Latest episode #7 (running)  $0.0431  in=18,204 out=2,910 tools=11

Recent activity
  4s ago [researcher] decision: top stories live at /v0/topstories.json, then /v0/item/<id>.json
  3s ago [coder] tool_call: write_file hn_digest.py (118 lines)
  1s ago [verifier] tool_call: run "python hn_digest.py --dry-run" -> printed 10 stories

Cumulative spend on this DB: $0.21
```

काम पूरा होने पर:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## रोकना / फिर से शुरू करना

अगर स्वार्म को कोई ऐसी जानकारी चाहिए जो केवल आप दे सकते हैं, तो वह रुक जाता है और सवाल को कतार में डाल देता है:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

लक्ष्य रीस्टार्ट के बाद भी बने रहते हैं। आप लैपटॉप बंद करके कल वापस आ सकते हैं।

## किसी देखे गए कार्य से अपना खुद का विशेषज्ञ बनाना

आपको किसी काम को शब्दों में बताने की ज़रूरत नहीं है — आप उसे दिखा सकते हैं। किसी व्यक्ति
को वह काम करते हुए का एक क्रमबद्ध रिकॉर्ड (उसने जो कार्रवाइयाँ कीं और क्यों कीं, उसका कोई
भी विवरण) JSONL या साधारण प्रीफ़िक्स्ड टेक्स्ट के रूप में कैप्चर करें, फिर वह फ़ाइल Lightwork
को सौंप दें:

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

यह डेमॉन्स्ट्रेशन को पार्स करता है, एक ड्राफ़्ट विशेषज्ञ तैयार करता है, आपको व्युत्पन्न
वर्कफ़्लो दिखाता है, और सहेजने से पहले आपकी मंज़ूरी का इंतज़ार करता है। सीक्रेट्स दरवाज़े पर ही
हटा दिए जाते हैं, और ड्राफ़्ट को वही कैपेबिलिटी क्लैंप और पर्सोना स्कैन मिलता है जो किसी
वर्णित पैक को मिलता है — आपकी हाँ के बिना कुछ भी सक्रिय नहीं होता। उपयोगी फ़्लैग्स:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` देखे गए चरणों को नियतात्मक रूप से प्रतिबिंबित करता है (टूल्स = जो व्यक्ति ने
इस्तेमाल किए); इसे हटा दें ताकि मॉडल ट्रांसक्रिप्ट से सुझाव दे सके।

जब आप किसी पैक को बातचीत के ज़रिए बनाते हैं, तब भी वही एजेंट-फ़ैक्टरी प्रवाह चलता है:

```bash
maverick onboard
```

मंज़ूरी मिलने पर, `onboard` अब पैक को प्रोविज़न करता है — यह उसके वर्कफ़्लो के लिए ज़रूरी
कैटलॉग स्किल्स इंस्टॉल करता है और किसी भी ऐसे घोषित टूल को संश्लेषित करता है जो पहले से
मौजूद नहीं है, ताकि एक नया-मंज़ूर किया गया विशेषज्ञ पहले ही रन से अपना काम करने के लिए
तैयार रहे। (यह चरण `[self_learning]` / `provision_packs` कॉन्फ़िगरेशन का सम्मान करता है और
पैक के क्लैंप्ड दायरे को कभी नहीं बढ़ाता।)

## मॉडल या प्रोवाइडर बदलना

विज़ार्ड को कभी भी दोबारा चलाएँ:

```bash
maverick init
```

या `~/.maverick/config.toml` को सीधे संपादित करें। `[models]` सेक्शन हर एजेंट रोल को एक `provider:model-id` स्ट्रिंग से मैप करता है। स्कीमा के लिए [`configuration.md`](../../configuration.md) देखें।

## डेटा कहाँ रहता है

| फ़ाइल | विवरण |
|---|---|
| `~/.maverick/config.toml` | आपका कॉन्फ़िगरेशन (डिप्लॉयमेंट, मॉडल, सेफ़्टी, बजट) |
| `~/.maverick/.env` | API कुंजियाँ (chmod 600) |
| `~/.maverick/world.db` | स्थायी वर्ल्ड मॉडल: लक्ष्य, तथ्य, एपिसोड |
| `~/.maverick/skills/` | सफल रन से अपने आप डिस्टिल की गई SKILL.md फ़ाइलें |
| `~/maverick-workspace/` | सैंडबॉक्स की डिफ़ॉल्ट वर्किंग डायरेक्टरी |
| `~/.maverick/learned-skills/` | लर्निंग लूप्स द्वारा डिस्टिल की गई स्किल्स |
| `~/.maverick/dreams/` | समेकित अंतर्दृष्टियाँ, रिहर्सल कतार, लर्निंग स्नैपशॉट्स |

सब कुछ लोकल रहता है। आपके चुने हुए क्लाउड LLM को भेजे जाने वाले प्रॉम्प्ट के अलावा कुछ भी अपलोड नहीं होता।

जब आपके पीछे कुछ रन हो जाएँ, तो लर्निंग सतह चार कमांड हैं:
`maverick dream` (अनुभव को समेकित करता है), `maverick hindsight` (क्या लर्निंग ने मदद की
या प्रतिगमन किया?), `maverick proof` (डिलिवरेबल्स, बचाई गई लागत, ROI), और
`maverick domains-lint` (2,020-एजेंट विशेषज्ञ कैटलॉग का ऑडिट), साथ ही
`maverick domains-audit` (गवर्नेंस स्थिति: हर एजेंट किस तक पहुँच सकता है, किसे अस्वीकार करता
है, और किसे मना करता है) और `maverick domains-eval --check` (व्यवहारगत गोल्डन केस)।
