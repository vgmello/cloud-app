import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";
import { howItWorks } from "./how-it-works";
import { capabilities } from "./capabilities";
import { environments } from "./environments";

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
];
