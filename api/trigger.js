module.exports = async function handler(req, res) {
  if (req.method !== "POST")
    return res.status(405).json({ error: "Method not allowed" });

  const REPO = process.env.GH_REPO;
  const TOKEN = process.env.GH_PAT;
  const BRANCH = process.env.GH_BRANCH || "main";

  if (!REPO || !TOKEN)
    return res.status(500).json({ error: "Sunucu yapılandırması eksik" });

  try {
    const statusRes = await fetch(
      `https://api.github.com/repos/${REPO}/contents/status.json`,
      { headers: { Authorization: `token ${TOKEN}` } }
    );
    if (statusRes.ok) {
      const statusData = await statusRes.json();
      const status = JSON.parse(Buffer.from(statusData.content, "base64").toString());
      if (status.status === "running") {
        return res.status(409).json({ error: "Zaten devam eden bir çeviri var" });
      }
    }

    await new Promise((r) => setTimeout(r, 2000));
    const dispatchRes = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/translate.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `token ${TOKEN}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: BRANCH }),
      }
    );

    if (!dispatchRes.ok) {
      const err = await dispatchRes.json();
      return res.status(500).json({ error: "Workflow tetiklenemedi", detail: err.message });
    }

    return res.json({ success: true });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "Sunucu hatası" });
  }
};
