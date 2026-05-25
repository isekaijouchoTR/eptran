export const config = { maxDuration: 10 };

export default async function handler(req, res) {
  if (req.method !== "GET")
    return res.status(405).json({ error: "Method not allowed" });

  const REPO = process.env.GH_REPO;
  const TOKEN = process.env.GH_PAT;

  if (!REPO || !TOKEN)
    return res.status(500).json({ error: "Sunucu yapılandırması eksik" });

  try {
    // Fetch status.json
    const statusRes = await fetch(
      `https://api.github.com/repos/${REPO}/contents/status.json`,
      { headers: { Authorization: `token ${TOKEN}` } }
    );

    if (!statusRes.ok) {
      return res.json({ status: "idle" });
    }

    const data = await statusRes.json();
    const status = JSON.parse(Buffer.from(data.content, "base64").toString());

    // Also fetch output file list if completed
    let outputFiles = [];
    if (status.status === "completed" && status.book) {
      const outputRes = await fetch(
        `https://api.github.com/repos/${REPO}/contents/output/${status.book}`,
        { headers: { Authorization: `token ${TOKEN}` } }
      );
      if (outputRes.ok) {
        const files = await outputRes.json();
        outputFiles = files
          .filter((f) => f.name.endsWith(".txt"))
          .map((f) => ({ name: f.name, download_url: f.download_url }));
      }
    }

    return res.json({ ...status, outputFiles });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "Sunucu hatası" });
  }
}
