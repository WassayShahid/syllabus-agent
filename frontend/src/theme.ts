import { defaultDarkModeOverride, Theme } from "@aws-amplify/ui-react";

/**
 * Amplify UI (the sign-in card) in the app's blue, following the system light/dark setting.
 * Components read `colors.primary` (by default an alias of the teal scale, which dark mode reverses),
 * so the scale is set directly for each colour mode.
 */
export const amplifyTheme: Theme = {
  name: "syllabus-agent",
  tokens: {
    colors: {
      primary: {
        10: "#e8eefc",
        20: "#d3defa",
        40: "#9fb6f3",
        60: "#5b7fe2",
        80: "#2f5bd3",
        90: "#284fba",
        100: "#2244a3",
      },
    },
    radii: { small: "8px", medium: "10px" },
  },
  overrides: [
    defaultDarkModeOverride,
    {
      colorMode: "dark",
      tokens: {
        colors: {
          primary: {
            10: "#23304f",
            20: "#2c3d66",
            40: "#4a63a8",
            60: "#6585d6",
            80: "#7d9cf0",
            90: "#9ab3f4",
            100: "#bccbf7",
          },
        },
      },
    },
  ],
};
