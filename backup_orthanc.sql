--
-- PostgreSQL database dump
--

\restrict vEtKJI61RVkZmcTTySgbNZdnlcI71EbgH3HYxzD6JHaJcfzP8yu5aCb0H1vi65R

-- Dumped from database version 15.18 (Debian 15.18-1.pgdg13+1)
-- Dumped by pg_dump version 15.18 (Debian 15.18-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: attachedfiledecrementsizefunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.attachedfiledecrementsizefunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO GlobalIntegersChanges VALUES(0, -old.compressedSize);
  INSERT INTO GlobalIntegersChanges VALUES(1, -old.uncompressedSize);
  RETURN NULL;
END;
$$;


ALTER FUNCTION public.attachedfiledecrementsizefunc() OWNER TO postgres;

--
-- Name: attachedfiledeletedfunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.attachedfiledeletedfunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO DeletedFiles VALUES
    (old.uuid, old.filetype, old.compressedSize,
     old.uncompressedSize, old.compressionType,
     old.uncompressedHash, old.compressedHash,
     old.revision, old.customData);
  RETURN NULL;
END;
$$;


ALTER FUNCTION public.attachedfiledeletedfunc() OWNER TO postgres;

--
-- Name: attachedfileincrementsizefunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.attachedfileincrementsizefunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO GlobalIntegersChanges VALUES(0, new.compressedSize);
  INSERT INTO GlobalIntegersChanges VALUES(1, new.uncompressedSize);
  RETURN NULL;
END;
$$;


ALTER FUNCTION public.attachedfileincrementsizefunc() OWNER TO postgres;

--
-- Name: computemissingchildcount(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.computemissingchildcount(batch_size bigint, OUT updated_rows_count bigint) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
BEGIN
	UPDATE Resources AS r
    SET childCount = (SELECT COUNT(childLevel.internalId)
                      FROM Resources AS childLevel
                      WHERE childLevel.parentId = r.internalId)
    WHERE internalId IN (
        SELECT internalId FROM Resources
        WHERE resourceType < 3 AND childCount IS NULL
        LIMIT batch_size);
    
    -- Get the number of rows affected
    GET DIAGNOSTICS updated_rows_count = ROW_COUNT;
END;
$$;


ALTER FUNCTION public.computemissingchildcount(batch_size bigint, OUT updated_rows_count bigint) OWNER TO postgres;

--
-- Name: computestatisticsreadonly(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.computestatisticsreadonly(statistics_key integer, OUT accumulated_value bigint) RETURNS bigint
    LANGUAGE plpgsql
    AS $$

DECLARE
    current_value BIGINT;
    
BEGIN

    SELECT VALUE FROM GlobalIntegers
    INTO current_value
    WHERE key = statistics_key;

    SELECT COALESCE(SUM(value), 0) + current_value FROM GlobalIntegersChanges
    INTO accumulated_value
    WHERE key = statistics_key;

END;
$$;


ALTER FUNCTION public.computestatisticsreadonly(statistics_key integer, OUT accumulated_value bigint) OWNER TO postgres;

--
-- Name: createdeletedfilestemporarytable(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.createdeletedfilestemporarytable() RETURNS void
    LANGUAGE plpgsql
    AS $$

BEGIN

    SET client_min_messages = warning;   -- suppress NOTICE:  relation "DeletedFiles" already exists, skipping

    -- note: temporary tables created at connection level -> they are likely to exist
    CREATE TEMPORARY TABLE IF NOT EXISTS DeletedFiles(
        uuid VARCHAR(64) NOT NULL,
        fileType INTEGER,
        compressedSize BIGINT,
        uncompressedSize BIGINT,
        compressionType INTEGER,
        uncompressedHash VARCHAR(40),
        compressedHash VARCHAR(40),
        revision INTEGER,
        customData BYTEA
        );

    RESET client_min_messages;

    -- clear the temporary table in case it has been created earlier in the connection
    DELETE FROM DeletedFiles;
END;

$$;


ALTER FUNCTION public.createdeletedfilestemporarytable() OWNER TO postgres;

--
-- Name: createinstance(text, text, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.createinstance(patient_public_id text, study_public_id text, series_public_id text, instance_public_id text, OUT is_new_patient bigint, OUT is_new_study bigint, OUT is_new_series bigint, OUT is_new_instance bigint, OUT patient_internal_id bigint, OUT study_internal_id bigint, OUT series_internal_id bigint, OUT instance_internal_id bigint) RETURNS record
    LANGUAGE plpgsql
    AS $$

BEGIN
	-- Assume the parent series already exists to minimize exceptions.  
    -- Most of the instances are not the first of their series - especially when we need high performances.

	is_new_patient := 1;
	is_new_study := 1;
	is_new_series := 1;
	is_new_instance := 1;

	-- First, check if the series already exists
	SELECT internalid INTO series_internal_id FROM "resources" WHERE publicId = series_public_id;

	IF series_internal_id IS NOT NULL THEN
	    -- RAISE NOTICE 'series-found %', series_internal_id;
		is_new_patient := 0;
		is_new_study := 0;
		is_new_series := 0;

		-- If the series exists, insert the instance directly
		BEGIN
			INSERT INTO "resources" VALUES (DEFAULT, 3, instance_public_id, series_internal_id, 0) RETURNING internalid INTO instance_internal_id;
		EXCEPTION
			WHEN unique_violation THEN
				is_new_instance := 0;
				SELECT internalid INTO instance_internal_id FROM "resources" WHERE publicId = instance_public_id;
		END;

    	SELECT internalid INTO patient_internal_id FROM "resources" WHERE publicId = patient_public_id;
		SELECT internalid INTO study_internal_id FROM "resources" WHERE publicId = study_public_id;

	ELSE
	    -- RAISE NOTICE 'series-not-found';

		-- If the series does not exist, execute the "full" steps
		BEGIN
			INSERT INTO "resources" VALUES (DEFAULT, 0, patient_public_id, NULL, 0) RETURNING internalid INTO patient_internal_id;
		EXCEPTION
			WHEN unique_violation THEN
				is_new_patient := 0;
				SELECT internalid INTO patient_internal_id FROM "resources" WHERE publicId = patient_public_id;
		END;
	
		BEGIN
			INSERT INTO "resources" VALUES (DEFAULT, 1, study_public_id, patient_internal_id, 0) RETURNING internalid INTO study_internal_id;
		EXCEPTION
			WHEN unique_violation THEN
				is_new_study := 0;
				SELECT internalid INTO study_internal_id FROM "resources" WHERE publicId = study_public_id;
		END;
	
		BEGIN
			INSERT INTO "resources" VALUES (DEFAULT, 2, series_public_id, study_internal_id, 0) RETURNING internalid INTO series_internal_id;
		EXCEPTION
			WHEN unique_violation THEN
				is_new_series := 0;
				SELECT internalid INTO series_internal_id FROM "resources" WHERE publicId = series_public_id;
		END;
	
		BEGIN
			INSERT INTO "resources" VALUES (DEFAULT, 3, instance_public_id, series_internal_id, 0) RETURNING internalid INTO instance_internal_id;
		EXCEPTION
			WHEN unique_violation THEN
				is_new_instance := 0;
				SELECT internalid INTO instance_internal_id FROM "resources" WHERE publicId = instance_public_id;
		END;

	END IF;


	IF is_new_instance > 0 THEN
		-- Move the patient to the end of the recycling order.
		PERFORM PatientAddedOrUpdated(patient_internal_id);
	END IF;
END;
$$;


ALTER FUNCTION public.createinstance(patient_public_id text, study_public_id text, series_public_id text, instance_public_id text, OUT is_new_patient bigint, OUT is_new_study bigint, OUT is_new_series bigint, OUT is_new_instance bigint, OUT patient_internal_id bigint, OUT study_internal_id bigint, OUT series_internal_id bigint, OUT instance_internal_id bigint) OWNER TO postgres;

--
-- Name: decrementresourcestrackerfunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.decrementresourcestrackerfunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO GlobalIntegersChanges VALUES(old.resourceType + 2, -1);
  RETURN NULL;
END;
$$;


ALTER FUNCTION public.decrementresourcestrackerfunc() OWNER TO postgres;

--
-- Name: deleteattachment(bigint, integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.deleteattachment(resource_id bigint, file_type integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- create/clear the DeletedFiles temporary table
    PERFORM CreateDeletedFilesTemporaryTable();

    DELETE FROM AttachedFiles WHERE id = resource_id AND fileType = file_type;
END;
$$;


ALTER FUNCTION public.deleteattachment(resource_id bigint, file_type integer) OWNER TO postgres;

--
-- Name: deleteresource(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.deleteresource(id bigint, OUT remaining_ancestor_resource_type integer, OUT remaining_anncestor_public_id text) RETURNS record
    LANGUAGE plpgsql
    AS $$

DECLARE
    deleted_resource_row RECORD;
    deleted_parent_row RECORD;
    deleted_grand_parent_row RECORD;
    deleted_grand_grand_parent_row RECORD;

    locked_parent_row RECORD;
    locked_resource_row RECORD;

BEGIN

    SET client_min_messages = warning;   -- suppress NOTICE:  relation "deletedresources" already exists, skipping

    -- note: temporary tables are created at connection level -> they are likely to exist.
    -- These tables are used by the triggers
    CREATE TEMPORARY TABLE IF NOT EXISTS DeletedResources(
        resourceType INTEGER NOT NULL,
        publicId VARCHAR(64) NOT NULL
        );

    RESET client_min_messages;

    -- clear the temporary table in case it has been created earlier in the connection
    DELETE FROM DeletedResources;

    -- create/clear the DeletedFiles temporary table
    PERFORM CreateDeletedFilesTemporaryTable();


    -- Before deleting an object, we need to lock its parent until the end of the transaction to avoid that
    -- 2 threads deletes the last 2 instances of a series at the same time -> none of them would realize
    -- that they are deleting the last instance and the parent resources would not be deleted.
    -- Locking only the immediate parent is sufficient to prevent from this.
    SELECT * INTO locked_parent_row FROM resources WHERE internalid = (SELECT parentid FROM resources WHERE internalid = id) FOR UPDATE;

    -- Before deleting the resource itself, we lock it to retrieve the resourceType and to make sure not 2 connections try to
    -- delete it at the same time
    SELECT * INTO locked_resource_row FROM resources WHERE internalid = id FOR UPDATE;

    -- before delete the resource itself, we must delete its grand-grand-children, the grand-children and its children no to violate 
    -- the parentId referencing an existing primary key constrain.  This is actually implementing the ON DELETE CASCADE that was on the parentId in previous revisions.
    
    -- If this resource has grand-grand-children, delete them
    if locked_resource_row.resourceType < 1 THEN
        WITH grand_grand_children_to_delete AS (SELECT grandGrandChildLevel.internalId, grandGrandChildLevel.resourceType, grandGrandChildLevel.publicId
                                                FROM Resources childLevel
                                                INNER JOIN Resources grandChildLevel ON childLevel.internalId = grandChildLevel.parentId
                                                INNER JOIN Resources grandGrandChildLevel ON grandChildLevel.internalId = grandGrandChildLevel.parentId
                                                WHERE childLevel.parentId = id),
        
        deleted_grand_grand_children_rows AS (DELETE FROM Resources WHERE internalId IN (SELECT internalId FROM grand_grand_children_to_delete)
                                              RETURNING resourceType, publicId)

        INSERT INTO DeletedResources SELECT resourceType, publicId FROM deleted_grand_grand_children_rows; 
    END IF;

    -- If this resource has grand-children, delete them
    if locked_resource_row.resourceType < 2 THEN
        WITH grand_children_to_delete AS (SELECT grandChildLevel.internalId, grandChildLevel.resourceType, grandChildLevel.publicId
                                          FROM Resources childLevel
                                          INNER JOIN Resources grandChildLevel ON childLevel.internalId = grandChildLevel.parentId
                                          WHERE childLevel.parentId = id),
        
        deleted_grand_children_rows AS (DELETE FROM Resources WHERE internalId IN (SELECT internalId FROM grand_children_to_delete)
                                        RETURNING resourceType, publicId)

        INSERT INTO DeletedResources SELECT resourceType, publicId FROM deleted_grand_children_rows; 
    END IF;

    -- If this resource has children, delete them
    if locked_resource_row.resourceType < 3 THEN
        WITH deleted_children AS (DELETE FROM Resources 
                                  WHERE parentId = id
                                  RETURNING resourceType, publicId)
        INSERT INTO DeletedResources SELECT resourceType, publicId FROM deleted_children; 
    END IF;


    -- delete the resource itself
    DELETE FROM Resources WHERE internalId=id RETURNING * INTO deleted_resource_row;

    -- keep track of the deleted resources for C++ code
    INSERT INTO DeletedResources VALUES (deleted_resource_row.resourceType, deleted_resource_row.publicId);
  
    -- If this resource still has siblings, keep track of the remaining parent
    -- (a parent that must not be deleted but whose LastUpdate must be updated)
    SELECT resourceType, publicId INTO remaining_ancestor_resource_type, remaining_anncestor_public_id
        FROM Resources 
        WHERE internalId = deleted_resource_row.parentId
            AND EXISTS (SELECT 1 FROM Resources WHERE parentId = deleted_resource_row.parentId);

	IF deleted_resource_row.resourceType > 0 THEN
        -- If this resource is the latest child, delete the parent
        DELETE FROM Resources WHERE internalId = deleted_resource_row.parentId
                                    AND NOT EXISTS (SELECT 1 FROM Resources WHERE parentId = deleted_resource_row.parentId)
                                    RETURNING * INTO deleted_parent_row;
        IF FOUND THEN
            INSERT INTO DeletedResources VALUES (deleted_parent_row.resourceType, deleted_parent_row.publicId);

            IF deleted_parent_row.resourceType > 0 THEN
                -- If this resource is the latest child, delete the parent
                DELETE FROM Resources WHERE internalId = deleted_parent_row.parentId
                                    AND NOT EXISTS (SELECT 1 FROM Resources WHERE parentId = deleted_parent_row.parentId)
                                    RETURNING * INTO deleted_grand_parent_row;
                IF FOUND THEN
                    INSERT INTO DeletedResources VALUES (deleted_grand_parent_row.resourceType, deleted_grand_parent_row.publicId);

                    IF deleted_grand_parent_row.resourceType > 0 THEN
                        -- If this resource is the latest child, delete the parent
                        DELETE FROM Resources WHERE internalId = deleted_grand_parent_row.parentId
                                            AND NOT EXISTS (SELECT 1 FROM Resources WHERE parentId = deleted_grand_parent_row.parentId)
                                            RETURNING * INTO deleted_grand_parent_row;
                        IF FOUND THEN
                            INSERT INTO DeletedResources VALUES (deleted_grand_parent_row.resourceType, deleted_grand_parent_row.publicId);
                        END IF;
                    END IF;
                END IF;
            END IF;
        END IF;
    END IF;

END;

$$;


ALTER FUNCTION public.deleteresource(id bigint, OUT remaining_ancestor_resource_type integer, OUT remaining_anncestor_public_id text) OWNER TO postgres;

--
-- Name: incrementresourcestrackerfunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.incrementresourcestrackerfunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO GlobalIntegersChanges VALUES(new.resourceType + 2, 1);
  RETURN NULL;
END;
$$;


ALTER FUNCTION public.incrementresourcestrackerfunc() OWNER TO postgres;

--
-- Name: insertedchangefunc(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.insertedchangefunc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE GlobalIntegers SET value = new.seq WHERE key = 6;
    RETURN NULL;
END;
$$;


ALTER FUNCTION public.insertedchangefunc() OWNER TO postgres;

--
-- Name: insertorupdatemetadata(bigint[], integer[], text[], integer[]); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.insertorupdatemetadata(resource_ids bigint[], metadata_types integer[], metadata_values text[], revisions integer[]) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
  	FOR i IN 1 .. ARRAY_LENGTH(resource_ids, 1) LOOP
		-- RAISE NOTICE 'Parameter %: % % %', i, resource_ids[i], metadata_types[i], metadata_values[i];
		INSERT INTO Metadata VALUES(resource_ids[i], metadata_types[i], metadata_values[i], revisions[i]) 
          ON CONFLICT (id, type) DO UPDATE SET value = EXCLUDED.value, revision = EXCLUDED.revision;
	END LOOP;
  
END;
$$;


ALTER FUNCTION public.insertorupdatemetadata(resource_ids bigint[], metadata_types integer[], metadata_values text[], revisions integer[]) OWNER TO postgres;

--
-- Name: patientaddedorupdated(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.patientaddedorupdated(patient_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DECLARE
        newSeq BIGINT;
    BEGIN
        INSERT INTO Metadata (id, type, value, revision)
        VALUES (patient_id, 19, nextval('PatientRecyclingOrderSequence')::TEXT, 0)
        ON CONFLICT (id, type)
        DO UPDATE SET value = EXCLUDED.value, revision = EXCLUDED.revision;
    END;
END;
$$;


ALTER FUNCTION public.patientaddedorupdated(patient_id bigint) OWNER TO postgres;

--
-- Name: protectpatient(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.protectpatient(patient_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO Metadata (id, type, value, revision) -- 18 = IsProtected
    VALUES (patient_id, 18, 'true', 0)
    ON CONFLICT (id, type)
    DO UPDATE SET value = EXCLUDED.value, revision = EXCLUDED.revision;
END;
$$;


ALTER FUNCTION public.protectpatient(patient_id bigint) OWNER TO postgres;

--
-- Name: unprotectpatient(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.unprotectpatient(patient_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM Metadata WHERE id = patient_id AND type = 18; -- 18 = IsProtected

    INSERT INTO Metadata (id, type, value, revision)
    VALUES (patient_id, 19, nextval('PatientRecyclingOrderSequence')::TEXT, 0)
    ON CONFLICT (id, type)
    DO UPDATE SET value = EXCLUDED.value, revision = EXCLUDED.revision;
END;
$$;


ALTER FUNCTION public.unprotectpatient(patient_id bigint) OWNER TO postgres;

--
-- Name: updatechildcount(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.updatechildcount() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
		IF new.parentId IS NOT NULL THEN
            -- mark the parent's childCount as invalid
			INSERT INTO InvalidChildCounts VALUES(new.parentId);
        END IF;
	
    ELSIF TG_OP = 'DELETE' THEN

		IF old.parentId IS NOT NULL THEN
            BEGIN
                -- mark the parent's childCount as invalid
                INSERT INTO InvalidChildCounts VALUES(old.parentId);
            EXCEPTION
                -- when deleting the last child of a parent, the insert will fail (this is expected)
                WHEN foreign_key_violation THEN NULL;
            END;
        END IF;
        
    END IF;
    RETURN NULL;
END;
$$;


ALTER FUNCTION public.updatechildcount() OWNER TO postgres;

--
-- Name: updateinvalidchildcounts(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.updateinvalidchildcounts(OUT updated_rows_count bigint) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
  locked_resources_ids BIGINT[];
BEGIN

    -- Lock the resources rows asap to prevent deadlocks
    -- that will need to be retried
    SELECT ARRAY(SELECT internalId
                 FROM Resources
                 WHERE internalId IN (SELECT DISTINCT id FROM InvalidChildCounts)
                 FOR UPDATE SKIP LOCKED)
    INTO locked_resources_ids;

    -- New rows can be added in the meantime, they won't be taken into account this time.
    WITH deleted_rows AS (
        DELETE FROM InvalidChildCounts
        WHERE id = ANY(locked_resources_ids)
        RETURNING id
    )

	UPDATE Resources
    SET childCount = (SELECT COUNT(childLevel.internalId)
                      FROM Resources AS childLevel
                      WHERE childLevel.parentId = Resources.internalId)
    WHERE internalid = ANY(locked_resources_ids);
    
    -- Get the number of rows affected
    GET DIAGNOSTICS updated_rows_count = ROW_COUNT;

END;
$$;


ALTER FUNCTION public.updateinvalidchildcounts(OUT updated_rows_count bigint) OWNER TO postgres;

--
-- Name: updatesinglestatistic(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.updatesinglestatistic(statistics_key integer, OUT new_value bigint) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
BEGIN

  -- Delete the current changes, sum them and update the GlobalIntegers row.
  -- New rows can be added in the meantime, they won't be deleted or summed.
  WITH rows_to_delete AS (
    SELECT ctid
    FROM GlobalIntegersChanges
    WHERE GlobalIntegersChanges.key = statistics_key
    LIMIT 10000                  -- by default, the UpdateSingleStatistics is called every seconds -> we should never get more than 10000 entries to compute so this is mainly useful to catch up with long standing entries from previous plugins version without the Housekeeping thread (see https://discourse.orthanc-server.org/t/increase-in-cpu-usage-of-database-after-update-to-orthanc-1-12-7/6057/6)
  ), 
  deleted_rows AS (
      DELETE FROM GlobalIntegersChanges
      WHERE GlobalIntegersChanges.ctid IN (SELECT ctid FROM rows_to_delete)
      RETURNING value
  )
  UPDATE GlobalIntegers
  SET value = value + (
      SELECT COALESCE(SUM(value), 0)
      FROM deleted_rows
  )
  WHERE GlobalIntegers.key = statistics_key
  RETURNING value INTO new_value;

END;
$$;


ALTER FUNCTION public.updatesinglestatistic(statistics_key integer, OUT new_value bigint) OWNER TO postgres;

--
-- Name: updatestatistics(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.updatestatistics(OUT patients_cunt bigint, OUT studies_count bigint, OUT series_count bigint, OUT instances_count bigint, OUT total_compressed_size bigint, OUT total_uncompressed_size bigint) RETURNS record
    LANGUAGE plpgsql
    AS $$
BEGIN

  SELECT UpdateSingleStatistic(0) INTO total_compressed_size;
  SELECT UpdateSingleStatistic(1) INTO total_uncompressed_size;
  SELECT UpdateSingleStatistic(2) INTO patients_cunt;
  SELECT UpdateSingleStatistic(3) INTO studies_count;
  SELECT UpdateSingleStatistic(4) INTO series_count;
  SELECT UpdateSingleStatistic(5) INTO instances_count;

END;
$$;


ALTER FUNCTION public.updatestatistics(OUT patients_cunt bigint, OUT studies_count bigint, OUT series_count bigint, OUT instances_count bigint, OUT total_compressed_size bigint, OUT total_uncompressed_size bigint) OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: attachedfiles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.attachedfiles (
    id bigint NOT NULL,
    filetype integer NOT NULL,
    uuid character varying(64) NOT NULL,
    compressedsize bigint,
    uncompressedsize bigint,
    compressiontype integer,
    uncompressedhash character varying(40),
    compressedhash character varying(40),
    revision integer,
    customdata bytea
);


ALTER TABLE public.attachedfiles OWNER TO postgres;

--
-- Name: auditlogs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auditlogs (
    ts timestamp without time zone DEFAULT now(),
    sourceplugin text NOT NULL,
    userid text NOT NULL,
    resourcetype integer NOT NULL,
    resourceid character varying(64) NOT NULL,
    action text NOT NULL,
    logdata bytea
);


ALTER TABLE public.auditlogs OWNER TO postgres;

--
-- Name: changes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.changes (
    seq bigint NOT NULL,
    changetype integer,
    internalid bigint,
    resourcetype integer,
    date character varying(64)
);


ALTER TABLE public.changes OWNER TO postgres;

--
-- Name: changes_seq_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.changes_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.changes_seq_seq OWNER TO postgres;

--
-- Name: changes_seq_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.changes_seq_seq OWNED BY public.changes.seq;


--
-- Name: dicomidentifiers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.dicomidentifiers (
    id bigint NOT NULL,
    taggroup integer NOT NULL,
    tagelement integer NOT NULL,
    value text
);


ALTER TABLE public.dicomidentifiers OWNER TO postgres;

--
-- Name: exportedresources; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.exportedresources (
    seq bigint NOT NULL,
    resourcetype integer,
    publicid character varying(64),
    remotemodality text,
    patientid character varying(64),
    studyinstanceuid text,
    seriesinstanceuid text,
    sopinstanceuid text,
    date character varying(64)
);


ALTER TABLE public.exportedresources OWNER TO postgres;

--
-- Name: exportedresources_seq_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.exportedresources_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.exportedresources_seq_seq OWNER TO postgres;

--
-- Name: exportedresources_seq_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.exportedresources_seq_seq OWNED BY public.exportedresources.seq;


--
-- Name: globalintegers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.globalintegers (
    key integer NOT NULL,
    value bigint
);


ALTER TABLE public.globalintegers OWNER TO postgres;

--
-- Name: globalintegerschanges; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.globalintegerschanges (
    key integer,
    value bigint
);


ALTER TABLE public.globalintegerschanges OWNER TO postgres;

--
-- Name: globalproperties; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.globalproperties (
    property integer NOT NULL,
    value text
);


ALTER TABLE public.globalproperties OWNER TO postgres;

--
-- Name: invalidchildcounts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.invalidchildcounts (
    id bigint,
    updatedat timestamp without time zone DEFAULT now()
);


ALTER TABLE public.invalidchildcounts OWNER TO postgres;

--
-- Name: keyvaluestores; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.keyvaluestores (
    storeid text NOT NULL,
    key text NOT NULL,
    value bytea NOT NULL
);


ALTER TABLE public.keyvaluestores OWNER TO postgres;

--
-- Name: labels; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.labels (
    id bigint NOT NULL,
    label text NOT NULL
);


ALTER TABLE public.labels OWNER TO postgres;

--
-- Name: maindicomtags; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.maindicomtags (
    id bigint NOT NULL,
    taggroup integer NOT NULL,
    tagelement integer NOT NULL,
    value text
);


ALTER TABLE public.maindicomtags OWNER TO postgres;

--
-- Name: metadata; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metadata (
    id bigint NOT NULL,
    type integer NOT NULL,
    value text,
    revision integer
);


ALTER TABLE public.metadata OWNER TO postgres;

--
-- Name: patientrecyclingordersequence; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.patientrecyclingordersequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.patientrecyclingordersequence OWNER TO postgres;

--
-- Name: queues; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.queues (
    id bigint NOT NULL,
    queueid text NOT NULL,
    value bytea NOT NULL
);


ALTER TABLE public.queues OWNER TO postgres;

--
-- Name: queues_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.queues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.queues_id_seq OWNER TO postgres;

--
-- Name: queues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.queues_id_seq OWNED BY public.queues.id;


--
-- Name: resources; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.resources (
    internalid bigint NOT NULL,
    resourcetype integer NOT NULL,
    publicid character varying(64) NOT NULL,
    parentid bigint,
    childcount integer
);


ALTER TABLE public.resources OWNER TO postgres;

--
-- Name: resources_internalid_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.resources_internalid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.resources_internalid_seq OWNER TO postgres;

--
-- Name: resources_internalid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.resources_internalid_seq OWNED BY public.resources.internalid;


--
-- Name: serverproperties; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.serverproperties (
    server character varying(64) NOT NULL,
    property integer NOT NULL,
    value text
);


ALTER TABLE public.serverproperties OWNER TO postgres;

--
-- Name: changes seq; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.changes ALTER COLUMN seq SET DEFAULT nextval('public.changes_seq_seq'::regclass);


--
-- Name: exportedresources seq; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.exportedresources ALTER COLUMN seq SET DEFAULT nextval('public.exportedresources_seq_seq'::regclass);


--
-- Name: queues id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.queues ALTER COLUMN id SET DEFAULT nextval('public.queues_id_seq'::regclass);


--
-- Name: resources internalid; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.resources ALTER COLUMN internalid SET DEFAULT nextval('public.resources_internalid_seq'::regclass);


--
-- Data for Name: attachedfiles; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.attachedfiles (id, filetype, uuid, compressedsize, uncompressedsize, compressiontype, uncompressedhash, compressedhash, revision, customdata) FROM stdin;
35748	1	f1a45e4e-83c8-4e08-8fb6-9084c1981807	151664	151664	1	1d95f8949822d9772d6b679ad895fcc5	1d95f8949822d9772d6b679ad895fcc5	0	\N
35752	1	1af0e786-c00b-4901-94dc-09ffd7e7047e	151664	151664	1	c7689048cb2bc04ca662ec451f337285	c7689048cb2bc04ca662ec451f337285	0	\N
35756	1	72a99d17-1f7f-4d29-9a40-71fcac0011f0	16184	16184	1	a1f3e83a768797207d50128394e6e788	a1f3e83a768797207d50128394e6e788	0	\N
35760	1	33591774-6867-4588-85e0-f18f50a54c16	9198	9198	1	1e278e3e72a351d9306ccc0cd5436ef4	1e278e3e72a351d9306ccc0cd5436ef4	0	\N
35764	1	b22f158d-e868-4a09-9c5e-57d001b17829	16192	16192	1	e747db227ad1c2aaad3d2a01de769696	e747db227ad1c2aaad3d2a01de769696	0	\N
35768	1	6a4edc29-fa55-4977-bb46-b5421d4cc159	16184	16184	1	0b764570f07602d0420b4f604eaa4857	0b764570f07602d0420b4f604eaa4857	0	\N
35772	1	1db76e76-747c-4d56-ae4f-ad617a1cc1ed	9198	9198	1	347ca0688a368499c7bd73b3ddc65f96	347ca0688a368499c7bd73b3ddc65f96	0	\N
35776	1	6d69aee1-ac5e-460e-a7e8-8b0ec4516064	9214	9214	1	ca19cd2cbfc2a83d1dc4a2d072cbb8fd	ca19cd2cbfc2a83d1dc4a2d072cbb8fd	0	\N
35747	4301	b407fc74-bcdd-4f75-9fe0-316945ccdcd9	699	699	1	937a40b706a42bb0eaf68d02d4e53693	937a40b706a42bb0eaf68d02d4e53693	0	\N
35751	4301	1586538d-f8ce-4ac1-ab6e-98aef9d0f754	697	697	1	8f6a37608c180e66a3e45158d857a235	8f6a37608c180e66a3e45158d857a235	1	\N
35755	4301	3b7d26eb-f968-4747-bfb9-d7588bc7e190	1887	1887	1	03bcfe6f79113cd7709053868ad0ecac	03bcfe6f79113cd7709053868ad0ecac	1	\N
35759	4301	953db5f2-c8d7-47b7-a363-ec539aa6ae2d	1757	1757	1	505735e09539f3a753d13d62ed2ce189	505735e09539f3a753d13d62ed2ce189	1	\N
35763	4301	d0d9ab65-6598-4de9-be3e-ab20d40bf6fa	1893	1893	1	75814574a7150bd6726070800a5e6bdf	75814574a7150bd6726070800a5e6bdf	1	\N
\.


--
-- Data for Name: auditlogs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.auditlogs (ts, sourceplugin, userid, resourcetype, resourceid, action, logdata) FROM stdin;
\.


--
-- Data for Name: changes; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.changes (seq, changetype, internalid, resourcetype, date) FROM stdin;
36193	14	35747	2	20260703T120139
36194	14	35751	2	20260703T120139
36195	15	35747	2	20260703T120139
36196	15	35751	2	20260703T120139
36197	14	35755	2	20260703T120143
36198	15	35755	2	20260703T120143
36199	14	35759	2	20260703T120144
36200	14	35763	2	20260703T120144
36201	13	35750	1	20260703T120144
36202	12	35749	0	20260703T120144
36203	15	35759	2	20260703T120144
36204	15	35763	2	20260703T120144
36169	2	35748	3	20260703T120038
36170	4	35747	2	20260703T120038
36171	5	35746	1	20260703T120038
36172	3	35745	0	20260703T120038
36173	2	35752	3	20260703T120038
36174	4	35751	2	20260703T120038
36175	5	35750	1	20260703T120038
36176	3	35749	0	20260703T120038
36177	2	35756	3	20260703T120042
36178	4	35755	2	20260703T120042
36179	2	35760	3	20260703T120043
36180	4	35759	2	20260703T120043
36181	2	35764	3	20260703T120043
36182	4	35763	2	20260703T120043
36183	2	35768	3	20260703T120044
36184	4	35767	2	20260703T120044
36185	2	35772	3	20260703T120044
36186	4	35771	2	20260703T120044
36187	2	35776	3	20260703T120045
36188	4	35775	2	20260703T120045
36189	15	35755	2	20260703T120046
36190	15	35759	2	20260703T120046
36191	15	35763	2	20260703T120046
36192	15	35751	2	20260703T120046
\.


--
-- Data for Name: dicomidentifiers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.dicomidentifiers (id, taggroup, tagelement, value) FROM stdin;
35748	8	24	1.2.826.0.1.3680043.10.47219117036788907173204258488660039104578
35747	32	14	1.2.826.0.1.3680043.10.14693038617622535132311656803458854870001
35746	16	32	PAT 2B074AFDF626
35746	16	16	ANONYMOUS
35746	16	48	
35746	32	13	1.2.826.0.1.3680043.10.32584618819212845926092711225432762489109
35746	8	80	
35746	8	4144	RETINAL FUNDUS PHOTOGRAPHY
35746	8	32	20260617
35745	16	32	PAT 2B074AFDF626
35745	16	16	ANONYMOUS
35745	16	48	
35752	8	24	1.2.826.0.1.3680043.10.51701900682805721594294807537432120732978
35751	32	14	1.2.826.0.1.3680043.10.14693038617622535132311656803458854870001
35750	16	32	PAT 2B88CB6E31CD
35750	16	16	ANONYMOUS
35750	16	48	
35750	32	13	1.2.826.0.1.3680043.10.13530843211848744398337792079929786408518
35750	8	80	
35750	8	4144	RETINAL FUNDUS PHOTOGRAPHY
35750	8	32	20260617
35749	16	32	PAT 2B88CB6E31CD
35749	16	16	ANONYMOUS
35749	16	48	
35756	8	24	1.2.826.0.1.3680043.8.498.30218620896421233015321067543451447933
35755	32	14	1.2.826.0.1.3680043.8.498.42921616485151915719334744262175594030
35760	8	24	1.2.826.0.1.3680043.8.498.99452594143937619195694760692265018768
35759	32	14	1.2.826.0.1.3680043.8.498.13454075828208582379951882681423059548
35764	8	24	1.2.826.0.1.3680043.8.498.10219297278927938840658889644485849600
35763	32	14	1.2.826.0.1.3680043.8.498.30547502906853599336932001717281940525
35768	8	24	1.2.826.0.1.3680043.8.498.12866472430061472790088147555562203852
35767	32	14	1.2.826.0.1.3680043.8.498.10412994638463554898220130894854593271
35772	8	24	1.2.826.0.1.3680043.8.498.22151683136880729683677098470943649236
35771	32	14	1.2.826.0.1.3680043.8.498.26215994956682466762958126300791181264
35776	8	24	1.2.826.0.1.3680043.8.498.25691447989441181896433624082366011307
35775	32	14	1.2.826.0.1.3680043.8.498.12272046370602954395737047575190805598
\.


--
-- Data for Name: exportedresources; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.exportedresources (seq, resourcetype, publicid, remotemodality, patientid, studyinstanceuid, seriesinstanceuid, sopinstanceuid, date) FROM stdin;
\.


--
-- Data for Name: globalintegers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.globalintegers (key, value) FROM stdin;
4	8
5	8
6	36204
0	386431
1	386431
2	2
3	2
\.


--
-- Data for Name: globalintegerschanges; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.globalintegerschanges (key, value) FROM stdin;
\.


--
-- Data for Name: globalproperties; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.globalproperties (property, value) FROM stdin;
1	6
4	6
6	1
10	1
11	3
12	1
13	1
14	1
\.


--
-- Data for Name: invalidchildcounts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.invalidchildcounts (id, updatedat) FROM stdin;
\.


--
-- Data for Name: keyvaluestores; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.keyvaluestores (storeid, key, value) FROM stdin;
\.


--
-- Data for Name: labels; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.labels (id, label) FROM stdin;
\.


--
-- Data for Name: maindicomtags; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.maindicomtags (id, taggroup, tagelement, value) FROM stdin;
35745	16	48	
35745	16	64	U
35775	8	112	pydicom-seg
35775	8	4158	lesion_seg
35775	32	14	1.2.826.0.1.3680043.8.498.12272046370602954395737047575190805598
35775	32	17	300
35748	8	24	1.2.826.0.1.3680043.10.47219117036788907173204258488660039104578
35748	32	19	1
35747	8	33	20260617
35747	8	49	212704
35747	8	96	OP
35747	8	112	OpenCode Synthetic Converter
35747	8	4158	Ophthalmic Photography - Moderate
35747	24	4144	Fundus Photography
35747	32	14	1.2.826.0.1.3680043.10.14693038617622535132311656803458854870001
35747	32	17	1
35746	16	16	Anonymous
35746	16	32	PAT_2b074afdf626
35746	16	48	
35746	16	64	U
35746	8	32	20260617
35746	8	48	212704
35746	8	80	
35746	8	128	SyntheticRetinaConverter
35746	8	4144	Retinal Fundus Photography
35746	32	13	1.2.826.0.1.3680043.10.32584618819212845926092711225432762489109
35746	32	16	1
35745	16	16	Anonymous
35745	16	32	PAT_2b074afdf626
35752	8	24	1.2.826.0.1.3680043.10.51701900682805721594294807537432120732978
35752	32	19	1
35751	8	33	20260617
35751	8	49	212704
35751	8	96	OP
35751	8	112	OpenCode Synthetic Converter
35751	8	4158	Ophthalmic Photography - Moderate
35751	24	4144	Fundus Photography
35751	32	14	1.2.826.0.1.3680043.10.14693038617622535132311656803458854870001
35751	32	17	1
35750	16	16	Anonymous
35750	16	32	PAT_2b88cb6e31cd
35750	16	48	
35750	16	64	U
35750	8	32	20260617
35750	8	48	212704
35750	8	80	
35750	8	128	SyntheticRetinaConverter
35750	8	4144	Retinal Fundus Photography
35750	32	13	1.2.826.0.1.3680043.10.13530843211848744398337792079929786408518
35750	32	16	1
35749	16	16	Anonymous
35749	16	32	PAT_2b88cb6e31cd
35749	16	48	
35749	16	64	U
35756	8	18	20260703
35756	8	19	120042.711386
35756	8	24	1.2.826.0.1.3680043.8.498.30218620896421233015321067543451447933
35756	32	19	1
35756	40	8	2
35755	8	33	20260703
35755	8	49	120042.711386
35755	8	96	SEG
35755	8	112	pydicom-seg
35755	8	4158	optic_disc_cup
35755	32	14	1.2.826.0.1.3680043.8.498.42921616485151915719334744262175594030
35755	32	17	300
35760	8	18	20260703
35760	8	19	120043.137571
35760	8	24	1.2.826.0.1.3680043.8.498.99452594143937619195694760692265018768
35760	32	19	1
35760	40	8	1
35759	8	33	20260703
35759	8	49	120043.137571
35759	8	96	SEG
35759	8	112	pydicom-seg
35759	8	4158	vessel_seg
35759	32	14	1.2.826.0.1.3680043.8.498.13454075828208582379951882681423059548
35759	32	17	300
35764	8	18	20260703
35764	8	19	120043.504675
35764	8	24	1.2.826.0.1.3680043.8.498.10219297278927938840658889644485849600
35764	32	19	1
35764	40	8	2
35763	8	33	20260703
35763	8	49	120043.504675
35763	8	96	SEG
35763	8	112	pydicom-seg
35763	8	4158	lesion_seg
35763	32	14	1.2.826.0.1.3680043.8.498.30547502906853599336932001717281940525
35763	32	17	300
35768	8	18	20260703
35768	8	19	120044.213370
35768	8	24	1.2.826.0.1.3680043.8.498.12866472430061472790088147555562203852
35768	32	19	1
35768	40	8	2
35767	8	33	20260703
35767	8	49	120044.213370
35767	8	96	SEG
35767	8	112	pydicom-seg
35767	8	4158	optic_disc_cup
35767	32	14	1.2.826.0.1.3680043.8.498.10412994638463554898220130894854593271
35767	32	17	300
35772	8	18	20260703
35772	8	19	120044.558206
35772	8	24	1.2.826.0.1.3680043.8.498.22151683136880729683677098470943649236
35772	32	19	1
35772	40	8	1
35771	8	33	20260703
35771	8	49	120044.558206
35771	8	96	SEG
35771	8	112	pydicom-seg
35771	8	4158	vessel_seg
35771	32	14	1.2.826.0.1.3680043.8.498.26215994956682466762958126300791181264
35771	32	17	300
35776	8	18	20260703
35776	8	19	120045.022877
35776	8	24	1.2.826.0.1.3680043.8.498.25691447989441181896433624082366011307
35776	32	19	1
35776	40	8	1
35775	8	33	20260703
35775	8	49	120045.022877
35775	8	96	SEG
\.


--
-- Data for Name: metadata; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.metadata (id, type, value, revision) FROM stdin;
35748	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35747	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35746	15	0008,0020;0008,0030;0008,0050;0008,0080;0008,0090;0008,0201;0008,1030;0020,000d;0020,0010;0032,1032;0032,1060	0
35745	15	0010,0010;0010,0020;0010,0030;0010,0040;0010,1000	0
35747	7	20260703T120038	0
35747	3		0
35748	2	20260703T120038	0
35748	3		0
35748	8	RestApi	0
35748	11	172.19.0.17	0
35748	13		0
35748	9	1.2.840.10008.1.2.1	0
35748	14	1124	0
35748	10	1.2.840.10008.5.1.4.1.1.77.1.5.1	0
35748	1	1	0
35752	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35751	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35750	15	0008,0020;0008,0030;0008,0050;0008,0080;0008,0090;0008,0201;0008,1030;0020,000d;0020,0010;0032,1032;0032,1060	0
35749	15	0010,0010;0010,0020;0010,0030;0010,0040;0010,1000	0
35751	7	20260703T120038	0
35751	3		0
35752	2	20260703T120038	0
35752	3		0
35752	8	RestApi	0
35752	11	172.19.0.17	0
35752	13		0
35752	9	1.2.840.10008.1.2.1	0
35752	14	1124	0
35752	10	1.2.840.10008.5.1.4.1.1.77.1.5.1	0
35752	1	1	0
35749	19	8702	0
35756	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35755	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35755	7	20260703T120042	0
35764	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35763	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35755	3		0
35756	2	20260703T120042	0
35756	3		0
35756	8	RestApi	0
35756	11	172.19.0.13	0
35756	13		0
35756	9	1.2.840.10008.1.2.1	0
35756	14	3628	0
35756	10	1.2.840.10008.5.1.4.1.1.66.4	0
35756	1	1	0
35760	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35759	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35759	7	20260703T120043	0
35772	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35771	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35759	3		0
35760	2	20260703T120043	0
35760	3		0
35760	8	RestApi	0
35760	11	172.19.0.13	0
35760	13		0
35760	9	1.2.840.10008.1.2.1	0
35760	14	2914	0
35760	10	1.2.840.10008.5.1.4.1.1.66.4	0
35760	1	1	0
35763	7	20260703T120043	0
35750	7	20260703T120043	0
35749	7	20260703T120043	0
35763	3		0
35764	2	20260703T120043	0
35764	3		0
35764	8	RestApi	0
35764	11	172.19.0.13	0
35764	13		0
35764	9	1.2.840.10008.1.2.1	0
35764	14	3636	0
35764	10	1.2.840.10008.5.1.4.1.1.66.4	0
35764	1	1	0
35745	19	8705	0
35768	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35767	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35767	7	20260703T120044	0
35767	3		0
35768	2	20260703T120044	0
35768	3		0
35768	8	RestApi	0
35768	11	172.19.0.13	0
35768	13		0
35768	9	1.2.840.10008.1.2.1	0
35768	14	3628	0
35768	10	1.2.840.10008.5.1.4.1.1.66.4	0
35768	1	1	0
35771	7	20260703T120044	0
35771	3		0
35772	2	20260703T120044	0
35772	3		0
35772	8	RestApi	0
35772	11	172.19.0.13	0
35772	13		0
35772	9	1.2.840.10008.1.2.1	0
35772	14	2914	0
35772	10	1.2.840.10008.5.1.4.1.1.66.4	0
35772	1	1	0
35776	15	0008,0012;0008,0013;0008,0018;0020,0012;0020,0013;0020,0032;0020,0037;0020,0100;0020,4000;0028,0008;0054,1330	0
35775	15	0008,0021;0008,0031;0008,0060;0008,0070;0008,0201;0008,1010;0008,103e;0008,1070;0018,0010;0018,0015;0018,0024;0018,1030;0018,1090;0018,1400;0020,000e;0020,0011;0020,0037;0020,0105;0020,1002;0040,0244;0040,0245;0040,0254;0040,0275;0054,0081;0054,0101;0054,1000	0
35775	7	20260703T120045	0
35746	7	20260703T120045	0
35745	7	20260703T120045	0
35775	3		0
35776	2	20260703T120045	0
35776	3		0
35776	8	RestApi	0
35776	11	172.19.0.13	0
35776	13		0
35776	9	1.2.840.10008.1.2.1	0
35776	14	2930	0
35776	10	1.2.840.10008.5.1.4.1.1.66.4	0
35776	1	1	0
\.


--
-- Data for Name: queues; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.queues (id, queueid, value) FROM stdin;
\.


--
-- Data for Name: resources; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.resources (internalid, resourcetype, publicid, parentid, childcount) FROM stdin;
35760	3	e40ef786-3f9652ab-69308f86-a04e2ec4-7cd20dc0	35759	0
35764	3	d56ad007-a4b5b643-f6fd4534-33593b0f-7962b741	35763	0
35759	2	15516945-20f1fd00-2a82c8be-205e9633-2f899551	35750	1
35763	2	7a169697-bc299fe0-b36a8efe-34aec564-4255f2cc	35750	1
35750	1	76bcdbfb-a0e6b422-62c37bcd-bee4d4ac-f0c9d474	35749	4
35768	3	54e16995-81ed2db9-ea036664-bda4f436-7d79b852	35767	0
35772	3	a2f5df49-a5a863c7-d4fbc0da-738ab196-1847f861	35771	0
35767	2	b4604813-a1dee878-16fc2a5a-09bdd0c5-968205a0	35746	1
35771	2	bc112db4-89a398ce-03d53dde-c4a1e52c-033ead02	35746	1
35748	3	58240bc1-a6b6e380-bc873a9e-e26a0ee6-936bb965	35747	0
35752	3	afce4d5d-17873de5-c5250b8f-2ee97bcf-5c1f21a5	35751	0
35745	0	871f709d-42f31513-ea8dcea3-f6c42f7f-7f1b26a6	\N	1
35747	2	c3f3f7cd-f367b064-70668bd1-b4e367d0-3bf8694d	35746	1
35749	0	e00de0c8-00974bdb-e17cd593-eb546f83-2b0a73c7	\N	1
35751	2	0bcc3407-a7755207-abc18dbd-b9cf6dd1-46b20a1f	35750	1
35756	3	7f0bc9de-d6d80035-d03b8704-ca0b826e-b1485473	35755	0
35755	2	d345aceb-bcf194fc-e9073e2c-86f263f2-6e303a7f	35750	1
35776	3	0db9dbe8-89eb2992-58409ef1-0fc512e0-2b1e9b30	35775	0
35746	1	fe9b9055-4a728370-cee2654d-482e4d3d-e2077a13	35745	4
35775	2	840d2c31-2ac3e3da-cdc063a3-642884c2-9e72468d	35746	1
\.


--
-- Data for Name: serverproperties; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.serverproperties (server, property, value) FROM stdin;
3d0eb8e6-3004ec90-63583983-b4b8cac5-ad4f47ab	5	{"Jobs":{},"Type":"JobsRegistry"}
83a45955-56d65607-5e863d7e-16f34443-81f784f1	5	{"Jobs":{},"Type":"JobsRegistry"}
ac422d63-6e92e679-76ec5a36-aaa29f15-b041e4f1	5	{"Jobs":{},"Type":"JobsRegistry"}
28fbc231-26564728-0f8ab6d0-0ad326bf-0f12e21d	5	{"Jobs":{},"Type":"JobsRegistry"}
af64fb51-9bbd4afb-35db4d87-1af4a281-7896bff9	5	{"Jobs":{},"Type":"JobsRegistry"}
1e05eb51-05cd3982-ab50baf9-aa53ebf4-cb2a2275	5	{"Jobs":{},"Type":"JobsRegistry"}
be3b6b91-57058474-47b6e49b-b3709428-0dfdf9e3	5	{"Jobs":{},"Type":"JobsRegistry"}
06219f81-cf2b6bb7-5e6e2697-b69623ff-796b7253	5	{"Jobs":{},"Type":"JobsRegistry"}
0d7197de-0b96b755-b238088f-3a8fe339-6326e961	5	{"Jobs":{},"Type":"JobsRegistry"}
6bb27a49-60300754-4cd21fd2-5dfdbd11-3aa42cd0	5	{"Jobs":{},"Type":"JobsRegistry"}
eeba3e66-51e57a28-a2a2396c-e8429345-3a51414d	5	{"Jobs":{},"Type":"JobsRegistry"}
f8f4da80-35be0b1c-46c40ba3-5855a9a4-c33e5ea7	5	{"Jobs":{},"Type":"JobsRegistry"}
162b4a2b-e3c4c8b5-e72a02f2-2d371bba-193df02b	5	{"Jobs":{},"Type":"JobsRegistry"}
5381270c-06a71b47-ecdde469-0f09f985-60bc174b	5	{"Jobs":{},"Type":"JobsRegistry"}
acc67f0f-dc28c0db-a180bd29-430167aa-3d06e004	5	{"Jobs":{},"Type":"JobsRegistry"}
c7f7fa67-f5f592de-c83f6a34-060c3528-1b914407	5	{"Jobs":{},"Type":"JobsRegistry"}
c57be7e4-650d13cb-5eadcbb0-dd56d280-a172152b	5	{"Jobs":{},"Type":"JobsRegistry"}
c27308b7-a30128ef-9f395ad0-ac722c9d-3713d07c	5	{"Jobs":{},"Type":"JobsRegistry"}
8201dc75-3947be1e-ed83f8f2-a5cbbd6b-867f18dc	5	{"Jobs":{},"Type":"JobsRegistry"}
667e53b1-5a0c8352-c130f016-b2233a38-aa471266	5	{"Jobs":{},"Type":"JobsRegistry"}
c05a60b6-be8fcf09-6f72538f-bc99a327-faae5899	5	{"Jobs":{},"Type":"JobsRegistry"}
4561ed72-22a34ce0-7f7d7af5-7c795dda-2f44354f	5	{"Jobs":{},"Type":"JobsRegistry"}
1ea8f1c0-1662994c-fd6ae088-238a5259-43f4ed6b	5	{"Jobs":{},"Type":"JobsRegistry"}
de2b4653-4720a875-06f899ae-ac3fe7e2-5b6e0b89	5	{"Jobs":{},"Type":"JobsRegistry"}
4abbab66-24011c02-650b94f6-3f00c1e0-7bfc6dc5	5	{"Jobs":{},"Type":"JobsRegistry"}
62915866-7d306da1-8c07f6fe-0a88db75-f1e8719d	5	{"Jobs":{},"Type":"JobsRegistry"}
c664f517-09e10487-5d077d93-7a90ce22-e962abe1	5	{"Jobs":{},"Type":"JobsRegistry"}
4f39aec5-3843f05e-3f7611f1-52b8a7ac-c522bf45	5	{"Jobs":{},"Type":"JobsRegistry"}
1d1bc414-4764894f-130d147e-7b23cd7f-9a8d920a	5	{"Jobs":{},"Type":"JobsRegistry"}
6ba195f9-cc0f6f36-b8e7e3ad-c8d09b99-a7be0a56	5	{"Jobs":{},"Type":"JobsRegistry"}
dc989e80-49fc8109-6b1e3db7-8eb27a5a-4e2c1a03	5	{"Jobs":{},"Type":"JobsRegistry"}
8a58c6ee-2d5cfc4b-0be3b9ff-11fef239-6d11c086	5	{"Jobs":{},"Type":"JobsRegistry"}
3b97a09d-04ae73d3-22ec3539-ba285a3e-a6569d53	5	{"Jobs":{},"Type":"JobsRegistry"}
d8a8b49c-da1c88cd-ea368274-92112799-ea8df4fc	5	{"Jobs":{},"Type":"JobsRegistry"}
5a849b36-cd910333-b85a4e1a-24061393-5aa5d976	5	{"Jobs":{},"Type":"JobsRegistry"}
9f8c7bbd-3769a860-ae5f1871-dcc27467-2bab9246	5	{"Jobs":{},"Type":"JobsRegistry"}
a7fb7cd3-9845b8c4-9c57c738-1f48007a-dd04b974	5	{"Jobs":{},"Type":"JobsRegistry"}
52c887ed-4135e717-d1683770-fcdc56ad-63cdda90	5	{"Jobs":{},"Type":"JobsRegistry"}
ab0f129f-c47ad3aa-821cb263-0579e101-dc143c59	5	{"Jobs":{},"Type":"JobsRegistry"}
a6e3a3f2-d0dea541-e1fbbbe8-49b69bbf-fdec9497	5	{"Jobs":{},"Type":"JobsRegistry"}
e51023f3-512741fa-375afb43-881a98d8-bc5c2db2	5	{"Jobs":{},"Type":"JobsRegistry"}
511484c9-72123432-d794c1a5-ef38f233-d7263b77	5	{"Jobs":{},"Type":"JobsRegistry"}
722d6644-0925fe1d-0074535b-eac28d2b-0c0e4f27	5	{"Jobs":{},"Type":"JobsRegistry"}
79a535f0-4a7c2787-f82514ca-5bb69f8f-75ad6d69	5	{"Jobs":{},"Type":"JobsRegistry"}
6acea2d2-3c23226d-2e4357d7-64125a66-1c60be85	5	{"Jobs":{},"Type":"JobsRegistry"}
f19505f7-69aec067-df0487b5-73aac20b-4034a317	5	{"Jobs":{},"Type":"JobsRegistry"}
48ac63be-41eb5381-8f6989d4-465fb3b2-971cb02d	5	{"Jobs":{},"Type":"JobsRegistry"}
87a9fe65-42ef44ed-a758f679-416bf0f7-cf58604b	5	{"Jobs":{},"Type":"JobsRegistry"}
8b5e1b30-d692bb2e-47a5a383-4dd5f545-11a46dec	5	{"Jobs":{},"Type":"JobsRegistry"}
e89ea603-eb56b9ba-13e6fb88-93cda6cf-e66d311b	5	{"Jobs":{},"Type":"JobsRegistry"}
df35a2ce-fc3cdcaa-c87cbdea-0c7e7d1e-cc665ac1	5	{"Jobs":{},"Type":"JobsRegistry"}
202745f7-924e8899-3e53191e-475331ed-35575daa	5	{"Jobs":{},"Type":"JobsRegistry"}
1b021669-372237f0-d90db4a8-89ff89d2-dbbb7996	5	{"Jobs":{},"Type":"JobsRegistry"}
2fe40fe1-85a3a9e3-49f7364d-8d57a71c-95e1a189	5	{"Jobs":{},"Type":"JobsRegistry"}
1080d943-7b9e6299-2e107b4a-cb79a890-2b0c8234	5	{"Jobs":{},"Type":"JobsRegistry"}
2403ebbb-8f0430a8-5acc13e8-b42918a4-7c2e7650	5	{"Jobs":{},"Type":"JobsRegistry"}
0d5098c6-4c66529f-ed169b4f-b7522580-b9ec2f99	5	{"Jobs":{},"Type":"JobsRegistry"}
60323ed2-f3ba5b36-6b3623e4-dfc91267-0e8e420b	5	{"Jobs":{},"Type":"JobsRegistry"}
2da06f6d-34519b93-061735a0-9aa491b0-6673f37c	5	{"Jobs":{},"Type":"JobsRegistry"}
a2ba7300-31b1ee22-07ca14b5-6f0a84e7-b2ef02f5	5	{"Jobs":{},"Type":"JobsRegistry"}
131f8445-d38acd05-5cdd0162-8b0862e5-56903c5d	5	{"Jobs":{},"Type":"JobsRegistry"}
3b3a5b25-017a0720-9a7ebb53-e185fda9-497dd381	5	{"Jobs":{},"Type":"JobsRegistry"}
0a383e1d-60262361-e27f6f69-fd5a8606-8d695a06	5	{"Jobs":{},"Type":"JobsRegistry"}
5791cc53-7d6cf294-21a8351b-b073993c-6dae2913	5	{"Jobs":{},"Type":"JobsRegistry"}
0be9fbb7-74ce9a83-d7b40d80-a3180118-896736e0	5	{"Jobs":{},"Type":"JobsRegistry"}
db31a871-f2521a4d-48185e8e-d5b158df-b4acd346	5	{"Jobs":{},"Type":"JobsRegistry"}
5b3deafa-0f41a9cd-44065b95-5f488cb0-26b01c59	5	{"Jobs":{},"Type":"JobsRegistry"}
bd4d07f5-ba4e4363-c0e80830-af8ac5b5-e341f908	5	{"Jobs":{},"Type":"JobsRegistry"}
dffde2e6-b6da6403-2065f8e3-003db1cb-59176020	5	{"Jobs":{},"Type":"JobsRegistry"}
a5a637ad-82652c9f-d5dbd817-1ac65d30-6f7ee274	5	{"Jobs":{},"Type":"JobsRegistry"}
b7ca608e-c6e5fba7-50164d4e-884a2cc7-2c5396e9	5	{"Jobs":{},"Type":"JobsRegistry"}
2179eb7a-6343199c-20fb3d8f-09352214-9cf1ba44	5	{"Jobs":{},"Type":"JobsRegistry"}
9ff49301-d91ae184-b9a4d042-2e746ffd-e1b7eaa8	5	{"Jobs":{},"Type":"JobsRegistry"}
0d8fd291-e00a5d1e-264e5bb9-da87b033-1c03d779	5	{"Jobs":{},"Type":"JobsRegistry"}
d689168c-d57ee34c-c0c0b062-9e133196-7fc2c068	5	{"Jobs":{},"Type":"JobsRegistry"}
21fe9fcf-ba4be50e-31031fe2-7e5efdc4-f3ca2bfb	5	{"Jobs":{},"Type":"JobsRegistry"}
b2a49272-5da4a15b-c2b1d827-8a3b08b5-fc9479d4	5	{"Jobs":{},"Type":"JobsRegistry"}
a1c8ffde-b78400a6-eb1a3f38-25540c69-c07d3171	5	{"Jobs":{},"Type":"JobsRegistry"}
3c1b195a-868a75d0-d3c20055-8eec591a-7670adf9	5	{"Jobs":{},"Type":"JobsRegistry"}
dfab12bc-4bf77435-6eb13678-47708595-1c581779	5	{"Jobs":{},"Type":"JobsRegistry"}
d9caab4d-4730529e-85e7caa8-951648ba-3eff1f15	5	{"Jobs":{},"Type":"JobsRegistry"}
5b9deaf1-e3e236a8-5b808fff-034e7e60-69bc05ef	5	{"Jobs":{},"Type":"JobsRegistry"}
1eee23f4-cfc1a133-7d56aeef-ab5fa05b-a1d8e871	5	{"Jobs":{},"Type":"JobsRegistry"}
818b8ad0-c4b5e1f1-c5db9cb4-c6e318b9-9e6ef592	5	{"Jobs":{},"Type":"JobsRegistry"}
8b251b29-cc3a4914-f00cfe51-a60070c2-a379032e	5	{"Jobs":{},"Type":"JobsRegistry"}
4a4e3e79-1cdb3682-b2e4f2df-42c1657d-a4cd33c7	5	{"Jobs":{},"Type":"JobsRegistry"}
b6608a8e-0c648afe-2db1fbfb-9b0ac365-dd136a75	5	{"Jobs":{},"Type":"JobsRegistry"}
245e1955-21e284e0-48b4433d-7d4a27ea-a18e0602	5	{"Jobs":{},"Type":"JobsRegistry"}
8965614a-8ec1ca22-f9b27fbf-1c55b86f-bc925e11	5	{"Jobs":{},"Type":"JobsRegistry"}
3cfb4750-3e2fd410-029b8c6c-66cd4fb8-e39d48aa	5	{"Jobs":{},"Type":"JobsRegistry"}
e2546fa5-31c9eb5f-bb5447d7-77789381-a246be34	5	{"Jobs":{},"Type":"JobsRegistry"}
d6ae95cc-d6378bee-dc0c9d67-25d94ed4-7faeff54	5	{"Jobs":{},"Type":"JobsRegistry"}
d47ba845-874f5e0e-002216f6-2ebfcf05-c4c87b1c	5	{"Jobs":{},"Type":"JobsRegistry"}
cbb80a37-687fc388-5d54dd2d-4563cd0f-f293c589	5	{"Jobs":{},"Type":"JobsRegistry"}
b661f6c2-47900176-15dc5187-28a6009d-49b7e440	5	{"Jobs":{},"Type":"JobsRegistry"}
88240fbe-f6f8f452-359d72db-b359f46e-f1175bf7	5	{"Jobs":{},"Type":"JobsRegistry"}
3e6e21a9-d518b6d0-5269cdf0-2fcfdb16-18411120	5	{"Jobs":{},"Type":"JobsRegistry"}
c3c66f59-2fad0240-496f94ff-df68f285-ebf7c6ec	5	{"Jobs":{},"Type":"JobsRegistry"}
9662d274-ba782071-e2952b21-f380aa87-8b4d35b0	5	{"Jobs":{},"Type":"JobsRegistry"}
eb7b8271-9f52b97f-54b1fe4e-e791e496-b71c7fbd	5	{"Jobs":{},"Type":"JobsRegistry"}
d52e4a6d-861cb540-e0e45111-2c4a8d3c-c09ac9f8	5	{"Jobs":{},"Type":"JobsRegistry"}
9dac1992-bc5ebca9-6303c0dd-4f12151a-1ee4fd11	5	{"Jobs":{},"Type":"JobsRegistry"}
33e3ed6c-5bc6b9c9-450b8fcb-6d7af974-0500fb9c	5	{"Jobs":{},"Type":"JobsRegistry"}
570ed03b-8c5210c0-08b9634a-cedb5f20-a40d015c	5	{"Jobs":{},"Type":"JobsRegistry"}
73910804-706005de-3d0e00a8-fc14b23c-27b1eed0	5	{"Jobs":{},"Type":"JobsRegistry"}
4aa6e50b-213c5dfc-0963596f-03525dd3-64343901	5	{"Jobs":{},"Type":"JobsRegistry"}
5abbb570-39d05e44-7325edc2-510ce75a-ad0d7cf3	5	{"Jobs":{},"Type":"JobsRegistry"}
e184762b-2c5b4cab-a3b50891-a17f08d2-38dfe19b	5	{"Jobs":{},"Type":"JobsRegistry"}
d93d7e76-e65b3dd2-c41a85cb-c4f0d4d6-2a9c75ae	5	{"Jobs":{},"Type":"JobsRegistry"}
827e8dc8-05c87656-969b6521-45009cca-6a8caf2c	5	{"Jobs":{},"Type":"JobsRegistry"}
22fee033-0f4fe135-1b86bdb0-0628e12f-dfd78dc5	5	{"Jobs":{},"Type":"JobsRegistry"}
135b6e58-a5ed824e-22f29be4-1625d153-ff3f7b2e	5	{"Jobs":{},"Type":"JobsRegistry"}
82a495c0-9ab8ac13-93b6a6f3-bd8a9ad3-b5400310	5	{"Jobs":{},"Type":"JobsRegistry"}
e31d9ed5-0393b489-927c847b-bf8673ce-5042b90f	5	{"Jobs":{},"Type":"JobsRegistry"}
9446bb5d-9a2c20e8-d2f72b0d-21b3b2c4-452de670	5	{"Jobs":{},"Type":"JobsRegistry"}
c72ea53d-7dc38231-24c44cb3-f34710f7-7f3639a5	5	{"Jobs":{},"Type":"JobsRegistry"}
289d8b02-3d7a36cb-cbc77d8c-0e9fa1dd-663801a9	5	{"Jobs":{},"Type":"JobsRegistry"}
fdf9e704-b1e305d0-968fbbd4-92bcc140-aa894487	5	{"Jobs":{},"Type":"JobsRegistry"}
99933c6e-f7a6edc5-80aafedb-a536d3c3-78fb0bc6	5	{"Jobs":{},"Type":"JobsRegistry"}
ba02ad69-6a9702fb-69dd3987-c2cad815-b4330f20	5	{"Jobs":{},"Type":"JobsRegistry"}
332830cd-bdb596f4-d43e49ae-fa310b5a-b0dc333c	5	{"Jobs":{},"Type":"JobsRegistry"}
86129de9-3775361c-0f458051-2d6e508d-b7048c63	5	{"Jobs":{},"Type":"JobsRegistry"}
3c664675-a9d86336-c1c5fadb-da05cbc9-21a0d8aa	5	{"Jobs":{},"Type":"JobsRegistry"}
139dbe0d-140c51ad-687a6e74-ae153c6f-d7f69567	5	{"Jobs":{},"Type":"JobsRegistry"}
cd9088de-8067e48a-b231d28e-35ab42ca-83a84340	5	{"Jobs":{},"Type":"JobsRegistry"}
d845f734-d9dcf9c7-f86177c3-625e4641-1450a479	5	{"Jobs":{},"Type":"JobsRegistry"}
d33b7699-721dceab-d803c9b6-804de1f7-a673803d	5	{"Jobs":{},"Type":"JobsRegistry"}
e0056903-29acab81-f9e13a40-b1cd67c9-7c1e266a	5	{"Jobs":{},"Type":"JobsRegistry"}
d6c43340-85410bb6-3ef83c88-4de788ee-2df5152e	5	{"Jobs":{},"Type":"JobsRegistry"}
8f43b7bc-5f15d81f-4a79d425-c8656a86-3888f151	5	{"Jobs":{},"Type":"JobsRegistry"}
f40a0249-1acd04ca-0367f384-3ccb1f4c-607a190c	5	{"Jobs":{},"Type":"JobsRegistry"}
ebc9d1de-2706e4be-6e2536ba-579a2a67-ed9d0df8	5	{"Jobs":{},"Type":"JobsRegistry"}
03ed9ad0-5321b694-d0eeaee2-9a20a64b-b16ba490	5	{"Jobs":{},"Type":"JobsRegistry"}
90659982-1fdc23e0-337caeb1-721df703-55dfbe63	5	{"Jobs":{},"Type":"JobsRegistry"}
08683d5f-ceb3ea0b-1c19e3e6-c83de4d1-7ae1184a	5	{"Jobs":{},"Type":"JobsRegistry"}
7db19762-9c9b0a21-d1bfe142-75020d13-296c32e6	5	{"Jobs":{},"Type":"JobsRegistry"}
74f4c76a-78e8b338-73b1f962-57f227ca-f40489f5	5	{"Jobs":{},"Type":"JobsRegistry"}
20505df5-5cf047e9-542a8568-51847b21-566d8088	5	{"Jobs":{},"Type":"JobsRegistry"}
4bbf5206-a850ec32-c92351b0-3904caba-7990919d	5	{"Jobs":{},"Type":"JobsRegistry"}
6199d844-720b8a67-e0f43e2b-fb85711d-ccfe4efb	5	{"Jobs":{},"Type":"JobsRegistry"}
332e3571-86ac66ff-f2f167a6-6e020816-6f92c4a0	5	{"Jobs":{},"Type":"JobsRegistry"}
86e16d09-642398e2-ff72651a-155a2f91-cc2e89bc	5	{"Jobs":{},"Type":"JobsRegistry"}
d5cc9eca-641b4c02-e04f7b63-82db5c61-8164d8cd	5	{"Jobs":{},"Type":"JobsRegistry"}
49113914-ca1131be-aa3c818e-b97a1b6c-019eda14	5	{"Jobs":{},"Type":"JobsRegistry"}
a12fe09c-84c0de85-da888170-40e93546-77c058f8	5	{"Jobs":{},"Type":"JobsRegistry"}
9898cf9c-cb50d20a-9603a374-05229829-72ddb3b1	5	{"Jobs":{},"Type":"JobsRegistry"}
6ed90379-03e954f0-5b917d15-8bfec9cc-826e93d2	5	{"Jobs":{},"Type":"JobsRegistry"}
bf432935-8a7c1ca1-1a5b233a-6d462ee9-ec9e4f8d	5	{"Jobs":{},"Type":"JobsRegistry"}
d93b8c0c-699b430d-aa2a06c1-c9a291dc-b3026a72	5	{"Jobs":{},"Type":"JobsRegistry"}
d120745d-336371d9-8c8f0f5d-480a96b2-b18d9e11	5	{"Jobs":{},"Type":"JobsRegistry"}
9fe352a8-5d8d784e-4f32b3cf-9c953c63-148d0348	5	{"Jobs":{},"Type":"JobsRegistry"}
ba867638-a09a40d5-504fd86e-d4d53b9e-b32c43e9	5	{"Jobs":{},"Type":"JobsRegistry"}
46f0b2e5-99e3fe93-c7a3e237-dd5deda1-ace0c4b2	5	{"Jobs":{},"Type":"JobsRegistry"}
0a41ebcc-ce661fcc-5536cd0f-0788d0bd-bdf30e30	5	{"Jobs":{},"Type":"JobsRegistry"}
5a1c69d2-7e9e0e38-ce28403c-3325f232-daaa0f05	5	{"Jobs":{},"Type":"JobsRegistry"}
738156c9-dd58d8b0-16e605ec-6cac222a-780501c8	5	{"Jobs":{},"Type":"JobsRegistry"}
87f690fc-03dc2406-11e5730a-3f53acc7-679c5345	5	{"Jobs":{},"Type":"JobsRegistry"}
a0b7816a-944b9d8b-7bee7980-2574b88d-b9c14886	5	{"Jobs":{},"Type":"JobsRegistry"}
219f9e79-6e8692a4-edc0b7dc-5f51389e-b2254fe8	5	{"Jobs":{},"Type":"JobsRegistry"}
be5780a1-989d2cdb-b2230775-fb93c064-75ec74c2	5	{"Jobs":{},"Type":"JobsRegistry"}
e7f73518-b96e26b3-69e9c7e6-c3d56c31-1900c9ee	5	{"Jobs":{},"Type":"JobsRegistry"}
9363b334-e9198f87-487dd468-ffe7e2c4-32d36302	5	{"Jobs":{},"Type":"JobsRegistry"}
9b145840-75fa8968-4b6e2891-8bf86e2e-e909ba56	5	{"Jobs":{},"Type":"JobsRegistry"}
c4e41063-f92887d5-76c43360-2a94dd31-2c5e47de	5	{"Jobs":{},"Type":"JobsRegistry"}
e361f3ff-c888ff77-949f1369-ce417dc2-787da748	5	{"Jobs":{},"Type":"JobsRegistry"}
e9b171f6-a772897a-558775bc-65afa1a8-c5851005	5	{"Jobs":{},"Type":"JobsRegistry"}
c75a65d6-7f4d8b1b-6728a772-8eb77be7-f907bdd3	5	{"Jobs":{},"Type":"JobsRegistry"}
5d4e4f7b-ea1a4eb1-809ffb8a-c9650de5-7651bd70	5	{"Jobs":{},"Type":"JobsRegistry"}
c76b9eeb-fffb7340-61fd2141-4f24ddf6-e5f02443	5	{"Jobs":{},"Type":"JobsRegistry"}
4550ef9d-2d998f9f-d007c2d9-e792362c-81729012	5	{"Jobs":{},"Type":"JobsRegistry"}
76abc823-4cc4228c-db5b8ec9-72a0f395-d66bbb09	5	{"Jobs":{},"Type":"JobsRegistry"}
fdeff492-c632fd32-dab8c06c-a59ae9ad-3caba6a9	5	{"Jobs":{},"Type":"JobsRegistry"}
4895f7a0-02b2b7f0-2ea89869-724076ca-f3b4cb60	5	{"Jobs":{},"Type":"JobsRegistry"}
045e73c6-2b72fda1-66ad0ce5-840d1515-eb5be169	5	{"Jobs":{},"Type":"JobsRegistry"}
dd2e0111-e918d213-5e37e03a-40106e8a-122ed2d4	5	{"Jobs":{},"Type":"JobsRegistry"}
d08365d0-83862395-f60c286e-7ff1b9fa-1f889f0c	5	{"Jobs":{},"Type":"JobsRegistry"}
53b926de-371fd3b2-41fbb7a1-41f32b78-5f4fdfa5	5	{"Jobs":{},"Type":"JobsRegistry"}
52a1c0f0-c098f83d-3c82e03b-6c28c036-7cb59579	5	{"Jobs":{},"Type":"JobsRegistry"}
bdc70e79-ca86bf39-da00ae61-8426043a-0d09b97d	5	{"Jobs":{},"Type":"JobsRegistry"}
30813a23-fdf2d2a4-5db5a411-fab7d538-6207e348	5	{"Jobs":{},"Type":"JobsRegistry"}
a7e19e06-bd4cc977-19dd75f2-9a6c7553-45fb2c3b	5	{"Jobs":{},"Type":"JobsRegistry"}
355cf2c1-46609892-b6d5818d-1aa925cc-d0596407	5	{"Jobs":{},"Type":"JobsRegistry"}
8a3a8cd7-1ae290df-85b16e95-5fb14b4b-116cc2ae	5	{"Jobs":{},"Type":"JobsRegistry"}
b1a82b63-a4c9eafc-953c6f07-071b93a5-09ed4b36	5	{"Jobs":{},"Type":"JobsRegistry"}
193ef8ab-8d8f16a8-1aea60df-8ace15eb-5dbfa303	5	{"Jobs":{},"Type":"JobsRegistry"}
f731e0c6-81d34b8d-7ea1be15-e85e6627-4d1eeb93	5	{"Jobs":{},"Type":"JobsRegistry"}
c0a72e14-13ae5016-b4146ede-e416f4bb-10c34195	5	{"Jobs":{},"Type":"JobsRegistry"}
25330ffa-3ba5639a-dff64d03-c185b2a6-d7737ba3	5	{"Jobs":{},"Type":"JobsRegistry"}
04a2749d-7e867cad-cbe78c16-0d41da1a-21e06071	5	{"Jobs":{},"Type":"JobsRegistry"}
f95871e3-65137cdb-536de5bf-4abbf849-de614999	5	{"Jobs":{},"Type":"JobsRegistry"}
43112cdd-e653ec10-7bf0f724-503d13df-88a1f00a	5	{"Jobs":{},"Type":"JobsRegistry"}
3f2ff037-c932de37-c4585935-b09de88f-2a6cd1b8	5	{"Jobs":{},"Type":"JobsRegistry"}
64a4ac7a-45ae6520-327281e5-7708dacb-8b7fd906	5	{"Jobs":{},"Type":"JobsRegistry"}
11cf750f-a4e36f77-f775bc3a-c4a5c89a-19eae289	5	{"Jobs":{},"Type":"JobsRegistry"}
8d62080e-d2d353a2-40f53745-8ef61712-7927706c	5	{"Jobs":{},"Type":"JobsRegistry"}
c9848d09-c0772b63-e366da36-699aa735-73c9046a	5	{"Jobs":{},"Type":"JobsRegistry"}
78457a87-5d110b88-d9a621bc-4c08a322-dffaa57d	5	{"Jobs":{},"Type":"JobsRegistry"}
7609e8c3-48cd9206-fa9359e3-93154581-5b30f1c0	5	{"Jobs":{},"Type":"JobsRegistry"}
cf88a737-f25aaf10-0620b8b8-df5ee935-7daff32f	5	{"Jobs":{},"Type":"JobsRegistry"}
25892409-70e950ba-5e3022d8-4de6048e-8d0a694e	5	{"Jobs":{},"Type":"JobsRegistry"}
9d73573e-68913138-eccaf36e-46df7f93-925de35a	5	{"Jobs":{},"Type":"JobsRegistry"}
005c79d3-c634c3d8-f985d38f-5fae99d1-05952eb6	5	{"Jobs":{},"Type":"JobsRegistry"}
ba6fa475-93d24d25-3f10cfee-d938a181-4179957b	5	{"Jobs":{},"Type":"JobsRegistry"}
dbfe8e8b-95b1b609-b47989b7-6e9881ab-1c6d4763	5	{"Jobs":{},"Type":"JobsRegistry"}
4e8a627b-db745a46-3a6f200a-d827e690-8a1b7fc1	5	{"Jobs":{},"Type":"JobsRegistry"}
869afcc9-312e403f-5ccb08f5-04508e91-18591c2f	5	{"Jobs":{},"Type":"JobsRegistry"}
aed969a9-e4483120-f183950f-29f19ad4-a916ba42	5	{"Jobs":{},"Type":"JobsRegistry"}
c9dd63d0-c4676a73-8ad9294b-88ab089f-3a8e1ff2	5	{"Jobs":{},"Type":"JobsRegistry"}
afaa40d7-24063ca3-4e9d17a9-e00c909a-ce376fee	5	{"Jobs":{},"Type":"JobsRegistry"}
45a3b24f-8a4782e6-d864d0d1-a9abb9db-1ca0c1c0	5	{"Jobs":{},"Type":"JobsRegistry"}
1f4bd93b-0bb90c2d-d41e17c2-a36ae5be-ba5feefe	5	{"Jobs":{},"Type":"JobsRegistry"}
880610b1-230cdd2d-f9f4fa8a-627fc48b-b850d53f	5	{"Jobs":{},"Type":"JobsRegistry"}
1fdb9722-a20507c1-595c071a-ff010a12-799bb41c	5	{"Jobs":{},"Type":"JobsRegistry"}
d2f547da-09809237-11a91274-98c4ead7-146a44ff	5	{"Jobs":{},"Type":"JobsRegistry"}
7e18df90-5331a50f-f302228f-77465d14-0e6cda6b	5	{"Jobs":{},"Type":"JobsRegistry"}
82f4c3d4-98878e66-ab3f6103-fb5f37c0-6528b506	5	{"Jobs":{},"Type":"JobsRegistry"}
efe0e8a3-af4a0de9-777bc87b-67f54c3f-e1f367db	5	{"Jobs":{},"Type":"JobsRegistry"}
9ec864f1-91e12de1-25af2bd0-2ba5d1dd-9c45f808	5	{"Jobs":{},"Type":"JobsRegistry"}
49787161-b5aae3ac-da6f562b-575cf56d-45dc89ef	5	{"Jobs":{},"Type":"JobsRegistry"}
65d17344-132c0719-ce867dcb-2b25c68e-48b8f662	5	{"Jobs":{},"Type":"JobsRegistry"}
4e2cde5c-f8c096c9-79e56618-ca31f3d9-82b9848d	5	{"Jobs":{},"Type":"JobsRegistry"}
93986be7-7df7b31a-53c08487-4a8208c0-f121992c	5	{"Jobs":{},"Type":"JobsRegistry"}
32bcf8c7-36135006-9e5cba43-48191f87-f0b6ff87	5	{"Jobs":{},"Type":"JobsRegistry"}
09d8a7b8-c8800986-ff864e41-ce76f7f4-812ac7a6	5	{"Jobs":{},"Type":"JobsRegistry"}
9cd1122a-7c6f905d-c1ea538b-432979aa-9fd29ec5	5	{"Jobs":{},"Type":"JobsRegistry"}
828ed5cd-93ba692b-abea6b8d-0fb650ba-f29d21d4	5	{"Jobs":{},"Type":"JobsRegistry"}
e0eaa171-999ad041-40246bb3-30f4240d-a41ef79a	5	{"Jobs":{},"Type":"JobsRegistry"}
f8d31c2b-8bac0842-7325324d-db1de401-0bac284f	5	{"Jobs":{},"Type":"JobsRegistry"}
4e3ab258-221ad350-83f1bc1d-4a2e15ed-1036b89e	5	{"Jobs":{},"Type":"JobsRegistry"}
2521ce23-909ce586-c4ef6ab2-56b79df4-8beebf8a	5	{"Jobs":{},"Type":"JobsRegistry"}
48d8eddb-01b8c990-3812a50b-fcfdab6f-09b93332	5	{"Jobs":{},"Type":"JobsRegistry"}
6ce5bff0-082b4a07-3f9a45b0-567bf334-335ab41e	5	{"Jobs":{},"Type":"JobsRegistry"}
290479a5-bd352ec5-82b147f9-c2fd3f5d-eb0ec0f8	5	{"Jobs":{},"Type":"JobsRegistry"}
398522b2-b4a42959-d4d041c5-a7ba1cc5-d688d365	5	{"Jobs":{},"Type":"JobsRegistry"}
47023211-7fddf64c-79b4ef2e-3a680bd7-837eccff	5	{"Jobs":{},"Type":"JobsRegistry"}
6e2e4283-8a519b9a-d3df816f-35266214-09d09440	5	{"Jobs":{},"Type":"JobsRegistry"}
01ee61f5-e008b27b-b329fa47-bb6b6168-7e78e025	5	{"Jobs":{},"Type":"JobsRegistry"}
adb0d884-476d036d-a859638e-29a34bfa-db398264	5	{"Jobs":{},"Type":"JobsRegistry"}
d2c86f77-52c2646c-67584488-ffb78a67-8508dab0	5	{"Jobs":{},"Type":"JobsRegistry"}
e4037cd8-20a7656d-83923632-5b637fe6-ddd70b82	5	{"Jobs":{},"Type":"JobsRegistry"}
a9b3486a-2f135ecf-11348975-b7407295-7baa6961	5	{"Jobs":{},"Type":"JobsRegistry"}
9bc50a61-47665a9c-a91d7b39-6e70e538-2d6abf1c	5	{"Jobs":{},"Type":"JobsRegistry"}
0ac976ac-dcead31f-2d2d9aba-1dbd9e3c-3cfee574	5	{"Jobs":{},"Type":"JobsRegistry"}
42e5812e-ddec0ac0-c4ca9d79-d4316d1a-2383751a	5	{"Jobs":{},"Type":"JobsRegistry"}
c1ba0475-d5a5ac4f-3423110a-3bdb2605-3d8470d8	5	{"Jobs":{},"Type":"JobsRegistry"}
913336d0-a459ea30-1f4c9b22-b560215c-b6231145	5	{"Jobs":{},"Type":"JobsRegistry"}
c63b1aa1-5d1fe3de-301eb63b-e7c27730-c726e971	5	{"Jobs":{},"Type":"JobsRegistry"}
ba41a7cf-a1780da2-109a8ad5-083ceda3-9ffa87ef	5	{"Jobs":{},"Type":"JobsRegistry"}
25cbb7c9-85d36e7d-9c11fd48-5aba25ce-91619594	5	{"Jobs":{},"Type":"JobsRegistry"}
66be51be-4cd47555-edc62965-22bfc5b2-e78655d8	5	{"Jobs":{},"Type":"JobsRegistry"}
d4ef7172-e4b6dec8-ab55dda0-5b8defa4-be49265a	5	{"Jobs":{},"Type":"JobsRegistry"}
76c1c9f8-1dce2ac2-954c7fca-41d4db9f-469e43f1	5	{"Jobs":{},"Type":"JobsRegistry"}
6683b6df-d77216c5-282668ee-a9e91329-cc5f7a88	5	{"Jobs":{},"Type":"JobsRegistry"}
e0d1b41e-6b4c4c43-426020f6-be36fa52-a9dca048	5	{"Jobs":{},"Type":"JobsRegistry"}
c156b0cf-f21fbb2b-51642cc6-66f674c4-9c9f74d0	5	{"Jobs":{},"Type":"JobsRegistry"}
c1a54b54-f8f5305f-5d6f04ec-d3554570-cb10ce36	5	{"Jobs":{},"Type":"JobsRegistry"}
cfb8a114-05037805-41e945fe-1e9c63cd-cfbfc067	5	{"Jobs":{},"Type":"JobsRegistry"}
bb512c17-ad85ae15-774f2507-6a2b222f-7d691397	5	{"Jobs":{},"Type":"JobsRegistry"}
31b2c7aa-4ce55940-ae9fe1d1-b68bf858-408f4ae5	5	{"Jobs":{},"Type":"JobsRegistry"}
54396c63-1ef07266-7da2157b-b3e48ac1-1abdeefd	5	{"Jobs":{},"Type":"JobsRegistry"}
1409491b-d20236d8-6bda06e9-08d97ece-e0598cfd	5	{"Jobs":{},"Type":"JobsRegistry"}
84a74f97-2ba56b84-6688be60-6a1523bf-b88681c7	5	{"Jobs":{},"Type":"JobsRegistry"}
b70162c2-04cac72d-2eaaa887-bf329901-fd46be3b	5	{"Jobs":{},"Type":"JobsRegistry"}
b7987607-5835b6a7-11ddfa06-2f22e4d1-1205bee2	5	{"Jobs":{},"Type":"JobsRegistry"}
5b4558d6-e9225ac8-f1cffc43-5d48cf19-f8d0b59d	5	{"Jobs":{},"Type":"JobsRegistry"}
64e7da3d-949e36a4-2b49cc3f-03257e21-caa8b775	5	{"Jobs":{},"Type":"JobsRegistry"}
06a16e85-b782896c-b90408f8-dc0ae1bd-65cc4a88	5	{"Jobs":{},"Type":"JobsRegistry"}
5546eccb-a0aebb89-19d8b02b-2948a24c-0d70d2f5	5	{"Jobs":{},"Type":"JobsRegistry"}
1608bacc-cd0f486a-e36ddf7f-818c0774-f8357694	5	{"Jobs":{},"Type":"JobsRegistry"}
644a8028-9e7c1c58-27879a8d-5beef653-85f0a516	5	{"Jobs":{},"Type":"JobsRegistry"}
6988dfe5-fe1c1fb4-dd71bddb-913dac7f-161d4dad	5	{"Jobs":{},"Type":"JobsRegistry"}
324ca883-8f15cd30-0bc01b40-e0b48073-309fbdae	5	{"Jobs":{},"Type":"JobsRegistry"}
244280ca-3f9d4034-ebf31fdb-3997ad0e-12dea417	5	{"Jobs":{},"Type":"JobsRegistry"}
34efb583-c8756de1-41a25b28-24ac9101-1a127a46	5	{"Jobs":{},"Type":"JobsRegistry"}
9ece91dd-ca2bd757-4bac07a7-cf74f63e-6e57aca4	5	{"Jobs":{},"Type":"JobsRegistry"}
bf356d21-4e20a13c-6eb405e0-2ec76b58-da051659	5	{"Jobs":{},"Type":"JobsRegistry"}
24e4ebe4-2384f281-011972d9-dcc59e88-078d635a	5	{"Jobs":{},"Type":"JobsRegistry"}
629d573a-967f7c6e-b27b69e6-edfd0ad9-80b63c12	5	{"Jobs":{},"Type":"JobsRegistry"}
d0931a79-5bc3ceb6-ac4ccb88-f8fe3643-249c0aef	5	{"Jobs":{},"Type":"JobsRegistry"}
6dfddd93-f4b13fb4-8eb4b68b-63aa5767-60f1cb19	5	{"Jobs":{},"Type":"JobsRegistry"}
deedd765-f358ef86-32ccf489-5d21574b-356a0290	5	{"Jobs":{},"Type":"JobsRegistry"}
67877c92-24e8a673-5e70ddf6-33432257-81c37695	5	{"Jobs":{},"Type":"JobsRegistry"}
8c50051b-c7688b8b-488bde88-1f3fc5b6-655c9336	5	{"Jobs":{},"Type":"JobsRegistry"}
20bc74f0-b06b8fc6-e78fafec-c5420124-43ff68e4	5	{"Jobs":{},"Type":"JobsRegistry"}
b50437f4-b48c093c-e3c59fd5-cbd73912-8b3b6ac3	5	{"Jobs":{},"Type":"JobsRegistry"}
594c223c-fa46c037-3a9e5797-9de9a091-2195f892	5	{"Jobs":{},"Type":"JobsRegistry"}
4b3ec78c-a9fcb873-bfdc96dc-7d15bfb4-e77ea7f4	5	{"Jobs":{},"Type":"JobsRegistry"}
761fed80-b00e4710-5217c2e4-ea7a8369-bee7e668	5	{"Jobs":{},"Type":"JobsRegistry"}
1220510e-9da4b5d9-4b91ebc8-720a4b3b-ce57a4a9	5	{"Jobs":{},"Type":"JobsRegistry"}
4903f026-0248038a-527a034b-422d72da-fd62df5d	5	{"Jobs":{},"Type":"JobsRegistry"}
4629e964-9b473dd4-30552337-c305c7e6-821d291d	5	{"Jobs":{},"Type":"JobsRegistry"}
79e4b90f-ebaf0536-cca7591b-fd6a7040-870572be	5	{"Jobs":{},"Type":"JobsRegistry"}
f463129a-98dc004c-f1ec9d51-63d41c9a-cdacb545	5	{"Jobs":{},"Type":"JobsRegistry"}
226622f1-c5480866-0259af2b-bd6b1514-6aa0e862	5	{"Jobs":{},"Type":"JobsRegistry"}
c7c244d0-d9709383-d99fc05a-9b34297b-ee3cf951	5	{"Jobs":{},"Type":"JobsRegistry"}
2036fe87-ceb7976b-a8612149-d9b20517-5784ab6c	5	{"Jobs":{},"Type":"JobsRegistry"}
474f7ffc-d3e66054-e124499d-198d6232-9c380e89	5	{"Jobs":{},"Type":"JobsRegistry"}
ee449a0b-1351349f-5cf7a325-77e0008b-a7e45c02	5	{"Jobs":{},"Type":"JobsRegistry"}
71ab8490-4bee3efa-1fba525e-956289d1-f4cdc4eb	5	{"Jobs":{},"Type":"JobsRegistry"}
25d68905-c59b51f4-85dfc6da-6728cdc7-754ed94e	5	{"Jobs":{},"Type":"JobsRegistry"}
77dec658-f6715104-f971556c-c23abf9d-0463b436	5	{"Jobs":{},"Type":"JobsRegistry"}
29b6dbb6-1617f433-81194402-3c82759a-4bc5acfc	5	{"Jobs":{},"Type":"JobsRegistry"}
ae4c2075-8cb7a8f7-5af53838-547d9ec9-33ea8612	5	{"Jobs":{},"Type":"JobsRegistry"}
c597161b-640948eb-30b02b12-577562a6-44c79018	5	{"Jobs":{},"Type":"JobsRegistry"}
7d086957-d1314a74-11a6b8d6-8c277698-4e52851e	5	{"Jobs":{},"Type":"JobsRegistry"}
087aa376-ce4185df-b757e429-11cef991-4ba31860	5	{"Jobs":{},"Type":"JobsRegistry"}
d8c2d6ab-05d96e4b-db19b8f1-79bc25b1-fed55ac6	5	{"Jobs":{},"Type":"JobsRegistry"}
edf990de-163603d4-c9a670a3-43edfa63-5e908424	5	{"Jobs":{},"Type":"JobsRegistry"}
efed422b-e6c0275f-b1c078a8-5b74bbc6-7ddd84e6	5	{"Jobs":{},"Type":"JobsRegistry"}
af477e14-4bba40cc-4470daee-afadc457-7639da06	5	{"Jobs":{},"Type":"JobsRegistry"}
87269981-4c1ef08e-2a0d8b4b-f7c54311-2423e9ff	5	{"Jobs":{},"Type":"JobsRegistry"}
e8fe9cc6-e87f0798-f19aa888-64a0320f-46ce8653	5	{"Jobs":{},"Type":"JobsRegistry"}
f9e59312-fb82dd4f-371e9efa-02e5fe4f-f3035d82	5	{"Jobs":{},"Type":"JobsRegistry"}
0980f8d4-a48b979c-4bc374ae-967733bb-278546f2	5	{"Jobs":{},"Type":"JobsRegistry"}
7fcbe84f-163d4a8f-74471cc9-ee7f7553-f7473fc2	5	{"Jobs":{},"Type":"JobsRegistry"}
f097a5c9-dbd35c85-4ec5f06c-47b455da-9e3dc88e	5	{"Jobs":{},"Type":"JobsRegistry"}
9b05f88c-b795221a-c7967c03-795a4299-a6a8e82d	5	{"Jobs":{},"Type":"JobsRegistry"}
7ec10e76-4613a6a7-ae95c496-dad10c55-7461d670	5	{"Jobs":{},"Type":"JobsRegistry"}
4472c15e-718d226d-996728a5-ce3ad323-ec4ba30b	5	{"Jobs":{},"Type":"JobsRegistry"}
7595d4e2-dc4b0e3d-ac7c3aa9-671437db-3ff848ad	5	{"Jobs":{},"Type":"JobsRegistry"}
c4070b07-87a741f4-7cd6e760-b98b49e0-014fa80a	5	{"Jobs":{},"Type":"JobsRegistry"}
ec2bf71a-9999b7f8-787db116-4aa99958-af13760b	5	{"Jobs":{},"Type":"JobsRegistry"}
67aa0e01-43623040-f7f5cb8b-8c1bf098-2e49a856	5	{"Jobs":{},"Type":"JobsRegistry"}
aa207117-0d3ab441-589ef5cc-d68106c4-1c6142aa	5	{"Jobs":{},"Type":"JobsRegistry"}
a21182c1-d2fdf9af-0ef9d0a8-d8d91c84-15ab833d	5	{"Jobs":{},"Type":"JobsRegistry"}
14fb3bad-06147fa8-7da10072-d12257ac-721967ce	5	{"Jobs":{},"Type":"JobsRegistry"}
3360ebdc-929344bb-0d0a87ac-555923ef-7c3ad093	5	{"Jobs":{},"Type":"JobsRegistry"}
3d5de28e-625fddb9-4867598c-277df870-7d411867	5	{"Jobs":{},"Type":"JobsRegistry"}
1fb89f77-c326a8bb-e4250a82-e328ba54-17394f7e	5	{"Jobs":{},"Type":"JobsRegistry"}
1df6a3ef-e6b431bb-7394513e-ea9b761d-c900ddcb	5	{"Jobs":{},"Type":"JobsRegistry"}
a31e19f9-2c351924-5862a045-ff2b2e92-82919b0f	5	{"Jobs":{},"Type":"JobsRegistry"}
\.


--
-- Name: changes_seq_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.changes_seq_seq', 36204, true);


--
-- Name: exportedresources_seq_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.exportedresources_seq_seq', 1, false);


--
-- Name: patientrecyclingordersequence; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.patientrecyclingordersequence', 8705, true);


--
-- Name: queues_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.queues_id_seq', 1, false);


--
-- Name: resources_internalid_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.resources_internalid_seq', 35776, true);


--
-- Name: attachedfiles attachedfiles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attachedfiles
    ADD CONSTRAINT attachedfiles_pkey PRIMARY KEY (id, filetype);


--
-- Name: changes changes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.changes
    ADD CONSTRAINT changes_pkey PRIMARY KEY (seq);


--
-- Name: dicomidentifiers dicomidentifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.dicomidentifiers
    ADD CONSTRAINT dicomidentifiers_pkey PRIMARY KEY (id, taggroup, tagelement);


--
-- Name: exportedresources exportedresources_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.exportedresources
    ADD CONSTRAINT exportedresources_pkey PRIMARY KEY (seq);


--
-- Name: globalintegers globalintegers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.globalintegers
    ADD CONSTRAINT globalintegers_pkey PRIMARY KEY (key);


--
-- Name: globalproperties globalproperties_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.globalproperties
    ADD CONSTRAINT globalproperties_pkey PRIMARY KEY (property);


--
-- Name: keyvaluestores keyvaluestores_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.keyvaluestores
    ADD CONSTRAINT keyvaluestores_pkey PRIMARY KEY (storeid, key);


--
-- Name: labels labels_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.labels
    ADD CONSTRAINT labels_pkey PRIMARY KEY (id, label);


--
-- Name: maindicomtags maindicomtags_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.maindicomtags
    ADD CONSTRAINT maindicomtags_pkey PRIMARY KEY (id, taggroup, tagelement);


--
-- Name: metadata metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata
    ADD CONSTRAINT metadata_pkey PRIMARY KEY (id, type);


--
-- Name: queues queues_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.queues
    ADD CONSTRAINT queues_pkey PRIMARY KEY (id);


--
-- Name: resources resources_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT resources_pkey PRIMARY KEY (internalid);


--
-- Name: serverproperties serverproperties_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.serverproperties
    ADD CONSTRAINT serverproperties_pkey PRIMARY KEY (server, property);


--
-- Name: resources uniquepublicid; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT uniquepublicid UNIQUE (publicid);


--
-- Name: auditlogsaction; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auditlogsaction ON public.auditlogs USING btree (action);


--
-- Name: auditlogsresourceid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auditlogsresourceid ON public.auditlogs USING btree (resourceid);


--
-- Name: auditlogssourceplugin; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auditlogssourceplugin ON public.auditlogs USING btree (sourceplugin);


--
-- Name: auditlogsuserid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auditlogsuserid ON public.auditlogs USING btree (userid);


--
-- Name: changesindex; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX changesindex ON public.changes USING btree (internalid);


--
-- Name: childrenindex2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX childrenindex2 ON public.resources USING btree (parentid) INCLUDE (publicid, internalid);


--
-- Name: dicomidentifiersindex1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX dicomidentifiersindex1 ON public.dicomidentifiers USING btree (id);


--
-- Name: dicomidentifiersindex2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX dicomidentifiersindex2 ON public.dicomidentifiers USING btree (taggroup, tagelement);


--
-- Name: dicomidentifiersindex3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX dicomidentifiersindex3 ON public.dicomidentifiers USING btree (taggroup, tagelement, value);


--
-- Name: dicomidentifiersindexvalues; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX dicomidentifiersindexvalues ON public.dicomidentifiers USING btree (value);


--
-- Name: dicomidentifiersindexvalues2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX dicomidentifiersindexvalues2 ON public.dicomidentifiers USING gin (value public.gin_trgm_ops);


--
-- Name: invalidchildcountsid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX invalidchildcountsid ON public.invalidchildcounts USING btree (id);


--
-- Name: labelsindex1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX labelsindex1 ON public.labels USING btree (id);


--
-- Name: labelsindex2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX labelsindex2 ON public.labels USING btree (label);


--
-- Name: maindicomtagsindex; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX maindicomtagsindex ON public.maindicomtags USING btree (id);


--
-- Name: publicindex; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX publicindex ON public.resources USING btree (publicid);


--
-- Name: queuesindex; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX queuesindex ON public.queues USING btree (queueid, id);


--
-- Name: resourcetypeindex; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX resourcetypeindex ON public.resources USING btree (resourcetype);


--
-- Name: attachedfiles attachedfiledecrementsize; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER attachedfiledecrementsize AFTER DELETE ON public.attachedfiles FOR EACH ROW EXECUTE FUNCTION public.attachedfiledecrementsizefunc();


--
-- Name: attachedfiles attachedfiledeleted; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER attachedfiledeleted AFTER DELETE ON public.attachedfiles FOR EACH ROW EXECUTE FUNCTION public.attachedfiledeletedfunc();


--
-- Name: attachedfiles attachedfileincrementsize; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER attachedfileincrementsize AFTER INSERT ON public.attachedfiles FOR EACH ROW EXECUTE FUNCTION public.attachedfileincrementsizefunc();


--
-- Name: resources decrementchildcount; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER decrementchildcount AFTER DELETE ON public.resources FOR EACH ROW WHEN ((old.parentid IS NOT NULL)) EXECUTE FUNCTION public.updatechildcount();


--
-- Name: resources decrementresourcestracker; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER decrementresourcestracker AFTER DELETE ON public.resources FOR EACH ROW EXECUTE FUNCTION public.decrementresourcestrackerfunc();


--
-- Name: resources incrementchildcount; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER incrementchildcount AFTER INSERT ON public.resources FOR EACH ROW EXECUTE FUNCTION public.updatechildcount();


--
-- Name: resources incrementresourcestracker; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER incrementresourcestracker AFTER INSERT ON public.resources FOR EACH ROW EXECUTE FUNCTION public.incrementresourcestrackerfunc();


--
-- Name: changes insertedchange; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER insertedchange AFTER INSERT ON public.changes FOR EACH ROW EXECUTE FUNCTION public.insertedchangefunc();


--
-- Name: attachedfiles attachedfiles_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attachedfiles
    ADD CONSTRAINT attachedfiles_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: changes changes_internalid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.changes
    ADD CONSTRAINT changes_internalid_fkey FOREIGN KEY (internalid) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: dicomidentifiers dicomidentifiers_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.dicomidentifiers
    ADD CONSTRAINT dicomidentifiers_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: invalidchildcounts invalidchildcounts_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invalidchildcounts
    ADD CONSTRAINT invalidchildcounts_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: labels labels_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.labels
    ADD CONSTRAINT labels_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: maindicomtags maindicomtags_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.maindicomtags
    ADD CONSTRAINT maindicomtags_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: metadata metadata_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metadata
    ADD CONSTRAINT metadata_id_fkey FOREIGN KEY (id) REFERENCES public.resources(internalid) ON DELETE CASCADE;


--
-- Name: resources resources_parentid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT resources_parentid_fkey FOREIGN KEY (parentid) REFERENCES public.resources(internalid);


--
-- PostgreSQL database dump complete
--

\unrestrict vEtKJI61RVkZmcTTySgbNZdnlcI71EbgH3HYxzD6JHaJcfzP8yu5aCb0H1vi65R

