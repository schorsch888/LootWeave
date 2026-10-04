import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api";
import type { Snapshot } from "../../shared/api";

type SavedProfile = { profile_id: string; revision: number; candidate_name: string; class_id: string; game_id: string };
type ProfileList = { profiles: SavedProfile[]; limit: number };
export type SavedProfileRevision = {
  profile_id: string;
  revision: number;
  facts: Snapshot;
  build_hash: string;
  facts_hash: string;
  observation_time_status?: string;
};

type Props = {
  busy?: boolean;
  onOpen: (profile: SavedProfileRevision) => void;
  onError: (message: string) => void;
  onBusyChange: (busy: boolean) => void;
  refreshKey: number | string;
};

export function ProfileLibrary({ onOpen, onError, onBusyChange, refreshKey, busy = false }: Props) {
  const [profiles, setProfiles] = useState<SavedProfile[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadingId, setLoadingId] = useState("");
  const [loadError, setLoadError] = useState("");
  const callbacks = useRef({ onOpen, onError, onBusyChange });
  const openRequestId = useRef(0);
  const openInFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    callbacks.current = { onOpen, onError, onBusyChange };
  }, [onOpen, onError, onBusyChange]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      openRequestId.current++;
    };
  }, []);

  useEffect(() => {
    let active = true;
    api<ProfileList>("profile/profiles")
      .then(result => {
        if (!active) return;
        setProfiles(result.profiles);
        setLoaded(true);
        setLoadError("");
      })
      .catch(error => {
        if (!active) return;
        const message = error instanceof Error ? error.message : "读取已保存档案失败。";
        setLoadError(message);
        callbacks.current.onError(message);
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  const openProfile = async (profile: SavedProfile) => {
    if (busy || openInFlight.current) return;
    openInFlight.current = true;
    const currentRequest = ++openRequestId.current;
    setLoadingId(profile.profile_id);
    callbacks.current.onBusyChange(true);
    try {
      const revision = await api<SavedProfileRevision>(
        `profile/profiles/${encodeURIComponent(profile.profile_id)}/revisions/${profile.revision}`,
      );
      if (mounted.current && openRequestId.current === currentRequest) callbacks.current.onOpen(revision);
    } catch (error) {
      if (mounted.current && openRequestId.current === currentRequest) {
        callbacks.current.onError(error instanceof Error ? error.message : "读取已保存档案失败。");
      }
    } finally {
      openInFlight.current = false;
      if (mounted.current && openRequestId.current === currentRequest) {
        setLoadingId("");
        callbacks.current.onBusyChange(false);
      }
    }
  };

  return <section className="panel">
    <details>
      <summary>已保存的角色档案</summary>
      <div aria-live="polite">
        {loadError && <p role="alert">{loadError}</p>}
        {!loaded && !loadError && <p className="muted">正在读取已保存档案…</p>}
        {loaded && profiles.length === 0 && <p className="muted">还没有已保存的角色档案。</p>}
        {profiles.map(profile => {
          const isLoading = loadingId === profile.profile_id;
          return <article className="reason" key={profile.profile_id}>
            <p><strong>{profile.candidate_name || "未命名候选物品"}</strong></p>
            <p>游戏：{profile.game_id} · 职业：{profile.class_id} · 修订 r{profile.revision}</p>
            <button type="button" onClick={() => void openProfile(profile)} disabled={busy || Boolean(loadingId)}>
              {isLoading ? "读取中…" : "打开此档案"}
            </button>
          </article>;
        })}
      </div>
    </details>
  </section>;
}
