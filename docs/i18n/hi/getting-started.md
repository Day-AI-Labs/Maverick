<!-- यह docs/getting-started.md (स्रोत कमिट: 001740b) का समुदाय-अनुरक्षित अनुवाद है — अंग्रेज़ी संस्करण ही आधिकारिक है। -->

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

सब कुछ लोकल रहता है। आपके चुने हुए क्लाउड LLM को भेजे जाने वाले प्रॉम्प्ट के अलावा कुछ भी अपलोड नहीं होता।
