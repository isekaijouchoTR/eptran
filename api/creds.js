module.exports = function handler(req, res) {
  if (req.method !== "GET")
    return res.status(405).json({ error: "Method not allowed" });

  const repo = process.env.GH_REPO;
  const pat = process.env.GH_PAT;
  const branch = process.env.GH_BRANCH || "main";

  if (!repo || !pat)
    return res.status(500).json({ error: "Sunucu yapılandırması eksik" });

  return res.json({ repo, branch, pat });
};
