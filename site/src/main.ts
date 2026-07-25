import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { initTabs } from "./behaviors/tabs";
import { initCopy } from "./behaviors/copy";

initTabs(document);
initCopy(document);
