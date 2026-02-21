package com.sentrius.sag.model;

public class UnsubscribeStatement implements Statement {
    private final String topic;

    public UnsubscribeStatement(String topic) {
        this.topic = topic;
    }

    public String getTopic() {
        return topic;
    }

    @Override
    public String toString() {
        return "UnsubscribeStatement{topic='" + topic + "'}";
    }
}
