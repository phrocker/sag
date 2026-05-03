package com.sentrius.sag;

import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * In-memory set of known agent ids, used by {@link SAGSanitizer}'s
 * Routing-Guard layer to reject messages whose source / destination is
 * not registered.
 *
 * <p>Mirrors the Python {@code sag.sanitizer.AgentRegistry} surface --
 * keep the two in lockstep so a message accepted by one runtime is
 * accepted by the other.
 */
public class AgentRegistry {
    private final Set<String> agents = Collections.synchronizedSet(new HashSet<>());

    public void register(String agentId) {
        if (agentId != null) {
            agents.add(agentId);
        }
    }

    public boolean isKnown(String agentId) {
        return agentId != null && agents.contains(agentId);
    }

    public void unregister(String agentId) {
        agents.remove(agentId);
    }

    public void clear() {
        agents.clear();
    }

    public int size() {
        return agents.size();
    }
}
