export const config = {
  maxDuration: 30,
  api: {
    bodyParser: {
      sizeLimit: "50mb",
    },
  },
};

export default async function handler(req, res) {
  if (req.method !== "POST")
    return res.status(405).json({ error: "Method not allowed" });

  const { filename, content } = req.body;

  if (!filename || !content)
    return res.status(400).json({ error: "filename ve content gerekli" });

  if (!filename.endsWith(".epub"))
    return res.status(400).json({ error: "Sadece .epub dosyaları kabul edilir" });

  const REPO = process.env.GH_REPO;
  const TOKEN = process.env.GH_PAT;
  const BRANCH = process.env.GH_BRANCH || "main";

  if (!REPO || !TOKEN)
    return res.status(500).json({ error: "Sunucu yapılandırması eksik" });

  try {
    // Check if a translation is already running
    const statusRes = await fetch(
      `https://api.github.com/repos/${REPO}/contents/status.json`,
      { headers: { Authorization: `token ${TOKEN}` } }
    );
    if (statusRes.ok) {
      const statusData = await statusRes.json();
      const status = JSON.parse(
        Buffer.from(statusData.content, "base64").toString()
      );
      if (status.status === "running") {
        return res
          .status(409)
          .json({ error: "Zaten devam eden bir çeviri var" });
      }
    }

    // Check if there's already a file in input/
    const inputRes = await fetch(
      `https://api.github.com/repos/${REPO}/contents/input`,
      { headers: { Authorization: `token ${TOKEN}` } }
    );
    if (inputRes.ok) {
      const files = await inputRes.json();
      const epubs = files.filter(
        (f) => f.name.endsWith(".epub") && f.name !== ".gitkeep"
      );
      if (epubs.length > 0) {
        return res
          .status(409)
          .json({ error: "input/ klasöründe zaten bir dosya var" });
      }
    }

    // Commit epub to input/
    const commitRes = await fetch(
      `https://api.github.com/repos/${REPO}/contents/input/${filename}`,
      {
        method: "PUT",
        headers: {
          Authorization: `token ${TOKEN}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: `upload: ${filename}`,
          content: content,
          branch: BRANCH,
        }),
      }
    );

    if (!commitRes.ok) {
      const err = await commitRes.json();
      return res
        .status(500)
        .json({ error: "GitHub commit başarısız", detail: err.message });
    }

    // Trigger workflow
    await new Promise((r) => setTimeout(r, 2000)); // push'un yayılmasını bekle
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
      return res
        .status(500)
        .json({ error: "Workflow tetiklenemedi" });
    }

    return res.json({ success: true, filename });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "Sunucu hatası" });
  }
}
