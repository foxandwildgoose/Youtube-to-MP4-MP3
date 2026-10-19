(function () {
  var theme = "system",
    lang = "ko";
  try {
    var savedTheme = localStorage.getItem("seorap-theme");
    var savedLang = localStorage.getItem("seorap-lang");
    if (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system")
      theme = savedTheme;
    if (savedLang === "en" || savedLang === "ko") lang = savedLang;
  } catch {
    /* Storage can be unavailable; keep safe defaults. */
  }
  var dark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.lang = lang;
})();
