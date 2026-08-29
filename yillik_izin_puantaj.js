
/* YILLIK İZİN PUANTAJ V2 */
(function () {
  function addAnnualLeaveOption(select) {
    if (!select || select.dataset.annualLeaveAdded) return;
    const exists = Array.from(select.options).some(o =>
      /yıllık izin|yillik izin/i.test(o.textContent || o.value || "")
    );
    if (!exists) {
      const opt = document.createElement("option");
      opt.value = "yillik_izin";
      opt.textContent = "Yıllık İzin";
      select.appendChild(opt);
    }
    select.dataset.annualLeaveAdded = "1";
  }

  function scan() {
    document.querySelectorAll("select").forEach(addAnnualLeaveOption);
  }

  document.addEventListener("DOMContentLoaded", scan);
  new MutationObserver(scan).observe(document.documentElement, {childList:true, subtree:true});
})();