import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [hero, manifestStack];
