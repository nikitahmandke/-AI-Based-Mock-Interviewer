const express = require("express");
const mysql = require("mysql2/promise");
const cors = require("cors");
require("dotenv").config();

const app = express();
app.use(cors());
app.use(express.json());

// Database connection function
async function createConnection() {
  try {
    return await mysql.createConnection({
      host: process.env.DB_HOST,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
      database: process.env.DB_NAME,
    });
  } catch (error) {
    console.log("Database not found, creating it...");

    // Create connection without database first
    const connection = await mysql.createConnection({
      host: process.env.DB_HOST,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
    });

    // Create database
    await connection.execute(
      `CREATE DATABASE IF NOT EXISTS ${process.env.DB_NAME}`
    );
    await connection.end();

    // Now connect to the database
    return await mysql.createConnection({
      host: process.env.DB_HOST,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
      database: process.env.DB_NAME,
    });
  }
}

// Initialize database
async function initializeDatabase() {
  try {
    const connection = await createConnection();

    console.log("✅ Connected to MySQL successfully!");

    // Create tables
    const tables = [
      `CREATE TABLE IF NOT EXISTS companies (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                requirements TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )`,

      `CREATE TABLE IF NOT EXISTS topics (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )`,

      `CREATE TABLE IF NOT EXISTS questions (
                id INT PRIMARY KEY AUTO_INCREMENT,
                title VARCHAR(500) NOT NULL,
                description TEXT,
                type ENUM('system_design', 'behavioral', 'data_structures', 'algorithms', 'other') NOT NULL,
                company_id INT,
                topic_id INT,
                views INT DEFAULT 0,
                likes INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
                FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
            )`,
    ];

    for (const tableSQL of tables) {
      await connection.execute(tableSQL);
    }

    // Insert sample data
    await insertSampleData(connection);
    await connection.end();

    console.log("✅ Database initialized successfully!");
  } catch (error) {
    console.error("❌ Database error:", error.message);
  }
}

// Insert sample data
async function insertSampleData(connection) {
  try {
    // Check if data exists
    const [companies] = await connection.execute(
      "SELECT COUNT(*) as count FROM companies"
    );
    if (companies[0].count > 0) {
      console.log("✅ Sample data already exists");
      return;
    }

    // Insert companies
    await connection.execute(
      "INSERT INTO companies (name, requirements) VALUES (?, ?)",
      [
        "Google",
        "Strong CS fundamentals, Proficiency in C++ or Java, Problem-solving skills",
      ]
    );
    await connection.execute(
      "INSERT INTO companies (name, requirements) VALUES (?, ?)",
      ["Meta", "System design, Algorithms, Behavioral skills"]
    );
    await connection.execute(
      "INSERT INTO companies (name, requirements) VALUES (?, ?)",
      ["Amazon", "Leadership principles, Data structures, System design"]
    );

    // Insert topics
    const topics = [
      "System Design",
      "Behavioral",
      "Data Structures",
      "Algorithms",
      "Database",
      "Networking",
    ];
    for (const topic of topics) {
      await connection.execute("INSERT INTO topics (name) VALUES (?)", [topic]);
    }

    // Get the inserted IDs
    const [google] = await connection.execute(
      "SELECT id FROM companies WHERE name = ?",
      ["Google"]
    );
    const [meta] = await connection.execute(
      "SELECT id FROM companies WHERE name = ?",
      ["Meta"]
    );
    const [amazon] = await connection.execute(
      "SELECT id FROM companies WHERE name = ?",
      ["Amazon"]
    );

    const [systemDesign] = await connection.execute(
      "SELECT id FROM topics WHERE name = ?",
      ["System Design"]
    );
    const [behavioral] = await connection.execute(
      "SELECT id FROM topics WHERE name = ?",
      ["Behavioral"]
    );
    const [dataStructures] = await connection.execute(
      "SELECT id FROM topics WHERE name = ?",
      ["Data Structures"]
    );

    // Insert questions
    await connection.execute(
      `INSERT INTO questions (title, description, type, company_id, topic_id, views, likes) 
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        "Design a URL shortening service like TinyURL",
        "Discuss the requirements, API design, data model, and how to handle hash collisions and generate unique short URLs. Consider scalability and performance.",
        "system_design",
        google[0].id,
        systemDesign[0].id,
        12500,
        3100,
      ]
    );

    await connection.execute(
      `INSERT INTO questions (title, description, type, company_id, topic_id, views, likes) 
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        "Tell me about a time you had a conflict with a coworker",
        "Describe the situation, the actions you took, and the outcome. Focus on your communication and problem-solving skills.",
        "behavioral",
        meta[0].id,
        behavioral[0].id,
        8200,
        1800,
      ]
    );

    await connection.execute(
      `INSERT INTO questions (title, description, type, company_id, topic_id, views, likes) 
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        "Find the median of two sorted arrays",
        "Given two sorted arrays, find the median of the two arrays efficiently.",
        "data_structures",
        amazon[0].id,
        dataStructures[0].id,
        6500,
        1200,
      ]
    );

    console.log("✅ Sample data inserted successfully!");
  } catch (error) {
    console.log("ℹ️ Sample data already exists or error:", error.message);
  }
}

// API Routes

// Get all questions with filters
app.get("/api/questions", async (req, res) => {
  try {
    const connection = await createConnection();
    const { company, topic, type, search } = req.query;

    let query = `
            SELECT 
                q.id, q.title, q.description, q.type, q.views, q.likes, q.created_at,
                c.name as company_name, c.requirements as company_requirements,
                t.name as topic_name
            FROM questions q
            LEFT JOIN companies c ON q.company_id = c.id
            LEFT JOIN topics t ON q.topic_id = t.id
            WHERE 1=1
        `;

    const params = [];

    if (company && company !== "all") {
      query += " AND c.name = ?";
      params.push(company);
    }

    if (topic && topic !== "all") {
      query += " AND t.name = ?";
      params.push(topic);
    }

    if (type && type !== "all") {
      query += " AND q.type = ?";
      params.push(type);
    }

    if (search) {
      query += " AND (q.title LIKE ? OR q.description LIKE ? OR c.name LIKE ?)";
      params.push(`%${search}%`, `%${search}%`, `%${search}%`);
    }

    query += " ORDER BY q.views DESC, q.likes DESC";

    const [questions] = await connection.execute(query, params);
    await connection.end();

    res.json(questions);
  } catch (error) {
    console.error("Error fetching questions:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Get all companies
app.get("/api/companies", async (req, res) => {
  try {
    const connection = await createConnection();
    const [companies] = await connection.execute(
      "SELECT * FROM companies ORDER BY name"
    );
    await connection.end();
    res.json(companies);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get all topics
app.get("/api/topics", async (req, res) => {
  try {
    const connection = await createConnection();
    const [topics] = await connection.execute(
      "SELECT * FROM topics ORDER BY name"
    );
    await connection.end();
    res.json(topics);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get question types
app.get("/api/question-types", async (req, res) => {
  try {
    const connection = await createConnection();
    const [types] = await connection.execute(
      "SELECT DISTINCT type FROM questions ORDER BY type"
    );
    await connection.end();
    res.json(types.map((t) => t.type));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Health check
app.get("/api/health", (req, res) => {
  res.json({ status: "OK", message: "Server is running with MySQL" });
});

// Start server
const PORT = process.env.PORT || 3000;
app.listen(PORT, async () => {
  console.log(`🚀 Server starting on port ${PORT}...`);
  await initializeDatabase();
  console.log(`✅ Server running on http://localhost:${PORT}`);
});
