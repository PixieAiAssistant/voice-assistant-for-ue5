/**
 * payment_config.js — централизованный конфиг платежных ссылок Pixie Pro.
 *
 * Все ссылки на платёжные провайдеры задаются здесь и динамически
 * подставляются в DOM при загрузке страницы. Это позволяет:
 * 1. Менять ссылки в одном месте
 * 2. Не светить их в HTML (защита от парсинга)
 * 3. Скрипты и URL платежей не зашиты в код
 */
const PIXIE_PAYMENT_CONFIG = {
  lava: {
    monthly: "https://app.lava.top/YOUR_PRODUCT_MONTHLY",
    yearly: "https://app.lava.top/YOUR_PRODUCT_YEARLY",
  },
  nowpayments: {
    crypto: "https://nowpayments.io/payment/?YOUR_NOWPAYMENTS_LINK",
  },
  // Базовый URL успешной оплаты (куда редиректит платёжка)
  successUrl: "https://pixie-ai.pro/success.html",
};

/**
 * Подставляет ссылки оплаты в элементы с data-payment-keys.
 * Пример: <a data-payment-key="lava_monthly" href="#">Buy Monthly</a>
 */
function applyPaymentLinks() {
  document.querySelectorAll("[data-payment-key]").forEach((el) => {
    const key = el.getAttribute("data-payment-key");
    let url = null;

    if (key === "lava_monthly") url = PIXIE_PAYMENT_CONFIG.lava.monthly;
    else if (key === "lava_yearly") url = PIXIE_PAYMENT_CONFIG.lava.yearly;
    else if (key === "nowpayments_crypto") url = PIXIE_PAYMENT_CONFIG.nowpayments.crypto;

    if (url) {
      el.setAttribute("href", url);
    }
  });
}

// Запускаем после загрузки DOM
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", applyPaymentLinks);
} else {
  applyPaymentLinks();
}