"use strict";

(() => {
  const runtime = window.MyPetsPortal;
  if (!runtime) {
    console.error("[MyPetsPortal] runtime missing before bootstrap");
    return;
  }
  runtime.markExtensionsReady();
  runtime.start().catch((error) => {
    console.error("[MyPetsPortal] startup failed", error);
  });
})();
