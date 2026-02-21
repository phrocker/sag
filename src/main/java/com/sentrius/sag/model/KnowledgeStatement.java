package com.sentrius.sag.model;

public class KnowledgeStatement implements Statement {
    private final String topic;
    private final Object value;
    private final int version;

    public KnowledgeStatement(String topic, Object value, int version) {
        this.topic = topic;
        this.value = value;
        this.version = version;
    }

    public String getTopic() {
        return topic;
    }

    public Object getValue() {
        return value;
    }

    public int getVersion() {
        return version;
    }

    @Override
    public String toString() {
        return "KnowledgeStatement{topic='" + topic + "', value=" + value + ", version=" + version + "}";
    }
}
