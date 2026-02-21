package com.sentrius.sag.model;

public class SubscribeStatement implements Statement {
    private final String topic;
    private final String filterExpr;

    public SubscribeStatement(String topic, String filterExpr) {
        this.topic = topic;
        this.filterExpr = filterExpr;
    }

    public String getTopic() {
        return topic;
    }

    public String getFilterExpr() {
        return filterExpr;
    }

    @Override
    public String toString() {
        return "SubscribeStatement{topic='" + topic + "'" +
               (filterExpr != null ? ", filter='" + filterExpr + "'" : "") + "}";
    }
}
