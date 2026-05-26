const { execFileSync } = require("child_process");

exports.default = async function adHocSignMac(context) {
  if (context.electronPlatformName !== "darwin") {
    return;
  }

  const appPath = context.appOutDir + "/" + context.packager.appInfo.productFilename + ".app";

  execFileSync(
    "codesign",
    ["--force", "--deep", "--sign", "-", "--timestamp=none", appPath],
    { stdio: "inherit" },
  );

  execFileSync("codesign", ["--verify", "--deep", "--strict", "--verbose=2", appPath], {
    stdio: "inherit",
  });
};
