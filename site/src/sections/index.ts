import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";
import { howItWorks } from "./how-it-works";
import { capabilities } from "./capabilities";
import { environments } from "./environments";
import { escapeHatch } from "./escape-hatch";
import { terraform } from "./terraform";
import { security } from "./security";
import { quickstart } from "./quickstart";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [
  hero,
  manifestStack,
  howItWorks,
  capabilities,
  environments,
  escapeHatch,
  terraform,
  security,
  quickstart,
];
