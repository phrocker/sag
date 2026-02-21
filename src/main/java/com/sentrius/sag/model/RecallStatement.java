package com.sentrius.sag.model;

public class RecallStatement implements Statement {
    private final String foldId;

    public RecallStatement(String foldId) {
        this.foldId = foldId;
    }

    public String getFoldId() {
        return foldId;
    }

    @Override
    public String toString() {
        return "RecallStatement{foldId='" + foldId + "'}";
    }
}
