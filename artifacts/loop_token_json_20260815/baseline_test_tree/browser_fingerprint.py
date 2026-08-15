import hashlib
import json
import random


DEFAULT_VIEWPORTS = (
    {"width": 1280, "height": 720, "screen_width": 1366, "screen_height": 768},
    {"width": 1365, "height": 768, "screen_width": 1366, "screen_height": 768},
    {"width": 1440, "height": 810, "screen_width": 1440, "screen_height": 900},
    {"width": 1536, "height": 824, "screen_width": 1536, "screen_height": 864},
    {"width": 1600, "height": 900, "screen_width": 1920, "screen_height": 1080},
)

DEFAULT_WEBGL_PROFILES = (
    {
        "vendor": "Google Inc. (Intel)",
        "renderer": (
            "ANGLE (Intel, Intel(R) UHD Graphics 630 "
            "(0x00003E92) Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
    },
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": (
            "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER "
            "(0x000021C4) Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
    },
    {
        "vendor": "Google Inc. (AMD)",
        "renderer": (
            "ANGLE (AMD, AMD Radeon RX 6600 XT "
            "(0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
    },
)


def chrome_major(browser_version):
    try:
        return int(str(browser_version).split(".", 1)[0])
    except (TypeError, ValueError):
        return 149


def create_fingerprint_profile(
    fingerprint_config,
    browser_version="",
    random_source=None,
):
    rng = random_source or random.SystemRandom()
    locale = fingerprint_config.get("locale", "en-US")
    timezone_id = fingerprint_config.get(
        "timezone_id",
        "America/Los_Angeles",
    )
    viewport = dict(rng.choice(DEFAULT_VIEWPORTS))
    webgl = dict(rng.choice(DEFAULT_WEBGL_PROFILES))
    major = chrome_major(browser_version)
    hardware_concurrency = rng.choice(
        fingerprint_config.get(
            "hardware_concurrency",
            [4, 8, 12, 16],
        )
    )
    device_memory = rng.choice(
        fingerprint_config.get("device_memory", [4, 8])
    )
    device_scale_factor = rng.choice(
        fingerprint_config.get(
            "device_scale_factor",
            [1, 1.25],
        )
    )
    languages = fingerprint_config.get(
        "languages",
        [locale, locale.split("-", 1)[0]],
    )
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )

    identity = json.dumps(
        {
            "locale": locale,
            "timezone": timezone_id,
            "viewport": viewport,
            "webgl": webgl,
            "hardwareConcurrency": hardware_concurrency,
            "deviceMemory": device_memory,
            "deviceScaleFactor": device_scale_factor,
            "userAgent": user_agent,
        },
        sort_keys=True,
    )
    profile_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]

    return {
        "profile_id": profile_id,
        "user_agent": user_agent,
        "platform": "Win32",
        "locale": locale,
        "languages": languages,
        "timezone_id": timezone_id,
        "viewport": {
            "width": viewport["width"],
            "height": viewport["height"],
        },
        "screen": {
            "width": viewport["screen_width"],
            "height": viewport["screen_height"],
        },
        "device_scale_factor": device_scale_factor,
        "hardware_concurrency": hardware_concurrency,
        "device_memory": device_memory,
        "max_touch_points": 0,
        "webgl_vendor": webgl["vendor"],
        "webgl_renderer": webgl["renderer"],
        "color_scheme": fingerprint_config.get(
            "color_scheme",
            "light",
        ),
        "geolocation": fingerprint_config.get("geolocation"),
    }


def build_context_options(profile):
    options = {
        "user_agent": profile["user_agent"],
        "viewport": profile["viewport"],
        "screen": profile["screen"],
        "locale": profile["locale"],
        "timezone_id": profile["timezone_id"],
        "color_scheme": profile["color_scheme"],
        "device_scale_factor": profile["device_scale_factor"],
        "is_mobile": False,
        "has_touch": False,
        "extra_http_headers": {
            "Accept-Language": ",".join(profile["languages"]),
        },
    }
    if profile.get("geolocation"):
        options["geolocation"] = profile["geolocation"]
        options["permissions"] = ["geolocation"]
    return options


def build_init_script(profile):
    payload = json.dumps(profile, ensure_ascii=False)
    return f"""
(() => {{
  const profile = {payload};
  const defineValue = (prototype, name, value) => {{
    try {{
      Object.defineProperty(prototype, name, {{
        configurable: true,
        get: () => value
      }});
    }} catch (_) {{}}
  }};

  defineValue(Navigator.prototype, "webdriver", undefined);
  defineValue(Navigator.prototype, "platform", profile.platform);
  defineValue(Navigator.prototype, "language", profile.languages[0]);
  defineValue(Navigator.prototype, "languages", Object.freeze(profile.languages));
  defineValue(
    Navigator.prototype,
    "hardwareConcurrency",
    profile.hardware_concurrency
  );
  defineValue(Navigator.prototype, "deviceMemory", profile.device_memory);
  defineValue(Navigator.prototype, "maxTouchPoints", profile.max_touch_points);

  const patchWebGL = (prototype) => {{
    if (!prototype || prototype.__fingerprintPatched) return;
    const original = prototype.getParameter;
    Object.defineProperty(prototype, "__fingerprintPatched", {{
      value: true
    }});
    prototype.getParameter = function(parameter) {{
      if (parameter === 37445) return profile.webgl_vendor;
      if (parameter === 37446) return profile.webgl_renderer;
      return original.call(this, parameter);
    }};
  }};

  patchWebGL(
    typeof WebGLRenderingContext !== "undefined"
      ? WebGLRenderingContext.prototype
      : null
  );
  patchWebGL(
    typeof WebGL2RenderingContext !== "undefined"
      ? WebGL2RenderingContext.prototype
      : null
  );

  Object.defineProperty(window, "__fingerprintProfileId", {{
    configurable: false,
    enumerable: false,
    value: profile.profile_id
  }});
}})();
"""


def build_launch_args(fingerprint_config):
    locale = fingerprint_config.get("locale", "en-US")
    return [
        "--disable-blink-features=AutomationControlled",
        f"--lang={locale}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
    ]


def apply_runtime_overrides(page, profile):
    page.evaluate(
        """
        profile => {
          const defineValue = (prototype, name, value) => {
            try {
              Object.defineProperty(prototype, name, {
                configurable: true,
                get: () => value
              });
            } catch (_) {}
          };

          defineValue(Navigator.prototype, "webdriver", undefined);
          defineValue(Navigator.prototype, "platform", profile.platform);
          defineValue(Navigator.prototype, "language", profile.languages[0]);
          defineValue(
            Navigator.prototype,
            "languages",
            Object.freeze(profile.languages)
          );
          defineValue(
            Navigator.prototype,
            "hardwareConcurrency",
            profile.hardware_concurrency
          );
          defineValue(
            Navigator.prototype,
            "deviceMemory",
            profile.device_memory
          );
          defineValue(
            Navigator.prototype,
            "maxTouchPoints",
            profile.max_touch_points
          );

          const patchWebGL = prototype => {
            if (!prototype || prototype.__fingerprintPatched) return;
            const original = prototype.getParameter;
            Object.defineProperty(prototype, "__fingerprintPatched", {
              value: true
            });
            prototype.getParameter = function(parameter) {
              if (parameter === 37445) return profile.webgl_vendor;
              if (parameter === 37446) return profile.webgl_renderer;
              return original.call(this, parameter);
            };
          };

          patchWebGL(
            typeof WebGLRenderingContext !== "undefined"
              ? WebGLRenderingContext.prototype
              : null
          );
          patchWebGL(
            typeof WebGL2RenderingContext !== "undefined"
              ? WebGL2RenderingContext.prototype
              : null
          );

          Object.defineProperty(window, "__fingerprintProfileId", {
            configurable: true,
            enumerable: false,
            value: profile.profile_id
          });
        }
        """,
        profile,
    )
