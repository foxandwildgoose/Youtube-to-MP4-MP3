(function () {
  try {
    var theme = localStorage.getItem("seorap-theme") || "system";
    var dark =
      theme === "dark" ||
      (theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    var lang = localStorage.getItem("seorap-lang");
    if (lang === "en" || lang === "ko") document.documentElement.lang = lang;
  } catch (e) {}
})();
