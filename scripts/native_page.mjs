export async function waitForNativePage(browser, deadline) {
  while (true) {
    const pages = browser.contexts().flatMap(context => context.pages());
    const page = pages.find(value => value.url().startsWith("http://127.0.0.1:"));
    if (page) return page;
    const remaining = deadline - Date.now();
    if (remaining <= 0) return undefined;
    await new Promise(resolve => setTimeout(resolve, Math.min(200, remaining)));
  }
}
