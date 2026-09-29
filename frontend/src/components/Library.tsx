import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../api/types";

/** Projects with their templates, for the Library, New shoot and the save dialogs. */

export function useProjects(): [Project[] | null, () => Promise<void>] {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const load = async () => {
    try {
      setProjects(await api.projects());
    } catch {
      setProjects([]);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  return [projects, load];
}
