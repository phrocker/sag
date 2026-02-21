package com.sentrius.sag.model;

import java.util.Map;

public class FoldStatement implements Statement {
    private final String foldId;
    private final String summary;
    private final Map<String, Object> state;

    public FoldStatement(String foldId, String summary, Map<String, Object> state) {
        this.foldId = foldId;
        this.summary = summary;
        this.state = state;
    }

    public String getFoldId() {
        return foldId;
    }

    public String getSummary() {
        return summary;
    }

    public Map<String, Object> getState() {
        return state;
    }

    @Override
    public String toString() {
        return "FoldStatement{foldId='" + foldId + "', summary='" + summary + "'}";
    }
}
