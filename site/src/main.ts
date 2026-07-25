import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { initTabs } from "./behaviors/tabs";
import { initCopy } from "./behaviors/copy";
import { initReveal } from "./behaviors/reveal";

initTabs(document);
initCopy(document);
initReveal(document);
